# std vs
from vapoursynth import core  # this may give a linter error, ignore
# std py
import os
import functools
import subprocess
# vs func repos
import havsfunc
# pypi dependencies
from pymediainfo import MediaInfo

class MpegProcessor():

    def __init__(self, filepath, source_cfg={}, dgindex_path="DGIndex.exe", debug=False):
        # source_cfg are key: value pairs that will be unpacked
        # and sent to the source used to load the clip. It will be
        # accessed with the source name as index, e.g. for core.d2v.Source:
        # source_cfg["core.d2v.Source"] will be used.
        # exports handy to parent
        self.clip = None
        self.clip_cfg = None
        self.clip_src = None
        self.fileid = None
        self.mediainfo = None
        self.standard = None
        # internal variables
        self.debug = debug
        self.filepath = filepath
        self.fileext = os.path.splitext(self.filepath)[-1].lower()[1:]
        self.fileinternal = None
        self.fileext = None
        self.dgindex_path = dgindex_path
        # get internal filepaths if exist
        if self.fileext == "d2v":  # DGIndex Project Files
            with open(self.filepath, mode="r") as f:
                # video filepath is always on line 3
                self.fileinternal = [l for i,l in enumerate(f) if i==2][0].strip()
            if self.fileinternal and not os.path.isabs(self.fileinternal):
                # convert relative to absolute
                self.fileinternal = os.path.join(os.path.dirname(self.filepath), self.fileinternal)
        # load mediainfo from MediaInfo
        self.mediainfo = [t for t in MediaInfo.parse(
            filename=self.fileinternal or self.filepath
        ).tracks if t.track_type == "Video"][0]
        # prepare a unique ID for input
        self.fileid = self.mediainfo.codec_id or self.mediainfo.commercial_name
        if self.fileid == "MPEG-2 Video":
            self.fileid = "V_MPEG2"
        elif self.fileid == "MPEG-1 Video":
            self.fileid = "V_MPEG1"
        # load file into clip with a Sourcer
        if self.fileid == "V_MPEG2":
            # core.d2v.Source is the only source available for frame-accuracy
            d2v_path = self.filepath
            if self.fileext != "d2v":
                # if the filepath isnt a d2v, force it to be
                d2v_path = f"{os.path.splitext(d2v_path)[0]}.d2v"
                if not os.path.exists(d2v_path):
                    # couldn't find d2v, generate one on-the-fly
                    mpg_path = f"{os.path.splitext(d2v_path)[0]}.mpg"
                    if not os.path.exists(mpg_path):
                        # couldn't find mpg, generate one on-the-fly
                        subprocess.run([
                            "mkvextract", os.path.basename(self.filepath),
                            "tracks", f"0:{os.path.basename(mpg_path)}"
                        ], cwd=os.path.dirname(self.filepath))
                    # generate d2v from mpg
                    subprocess.run([
                        self.dgindex_path,
                        "-i", os.path.basename(mpg_path),
                        "-ia", "5",  # iDCT Algorithm, 5=IEEE-1180 Reference
                        "-fo", "2",  # Field Operation, 2=Ignore Pulldown Flags
                        "-yr", "1",  # YUV->RGB, 1=PC Scale
                        "-om", "0",  # Output Method, 0=None (just d2v)
                        "-hide", "-exit",  # start hidden and exit when saved
                        "-o", os.path.splitext(os.path.basename(d2v_path))[0]
                    ], cwd=os.path.dirname(d2v_path))
                    # make sure d2v's internal mpg file path is relative to mpg directory
                    with open(d2v_path, mode="r") as f:
                        _D2V = f.read().splitlines()
                    _D2V[2] = os.path.basename(mpg_path)
                    with open(d2v_path, mode="w") as f:
                        f.write("\n".join(_D2V))
            self.clip_cfg = {
                **(source_cfg["core.d2v.Source"] if "core.d2v.Source" in source_cfg else {}),
                "input": d2v_path
            }
            self.clip_src = "d2v"
            self.clip = core.d2v.Source(**self.clip_cfg)
            if "rff" in self.clip_cfg and not self.clip_cfg["rff"]:
                if self.clip.fps.numerator == 30000 and self.clip.fps.denominator == 1001:
                    # Fix core.d2v.Source's NTSC rff=False returned FPS, though right now, it's
                    # just assuming rff=False is returning 24000/1001 (FILM~) frame rate because NTSC.
                    self.clip = core.std.AssumeFPS(self.clip, fpsnum=24000, fpsden=1001)
                if self.debug:
                    self.clip = core.text.Text(self.clip, "Untouched Frame (rff=False)", alignment=1)
        elif self.fileid in ["V_MPEG1", "V_MPEG4/ISO/AVC"]:
            self.clip_cfg = {
                **(source_cfg["core.ffms2.Source"] if "core.ffms2.Source" in source_cfg else {}),
                "source": self.filepath,
                "alpha": False
            }
            self.clip_src = "ffms2"
            self.clip = core.ffms2.Source(**self.clip_cfg)
        else:
            raise ValueError(f"Video Codec ({self.fileid}) not currently supported")
        # detect standard
        if self.clip.fps.numerator == 25 and self.clip.fps.denominator == 1 and self.clip.width == 720 and self.clip.height == 576:
            self.standard = "PAL"
        elif self.clip.fps.numerator == 30000 and self.clip.fps.denominator == 1001 and self.clip.width == 720 and self.clip.height == 480:
            self.standard = "NTSC"

    def deinterlace(self, vfm_cfg={}, qtgmc_cfg={}, tff=None):
        if tff is None:
            # try get tff from first first frame
            # todo ; try figure out a better way to get tff, as this may not be accurate
            first_frame = self.clip.get_frame(0).props
            if "_FieldBased" in first_frame:
                tff = first_frame["_FieldBased"] != 1  # if its 0=frame or 2=top, tff=True
        if "FPSDivisor" in qtgmc_cfg and qtgmc_cfg["FPSDivisor"] == 1:
            # we need a clip with double the frame rate and double frame length to hold qtgmc's Double-rate frames
            format_clip = core.std.BlankClip(
                clip=self.clip,
                length=len(self.clip)*2,
                fpsnum=self.clip.fps.numerator*2,
                fpsden=self.clip.fps.denominator
            )
        else:
            format_clip = self.clip
        # prepare vfm
        vfm = core.vivtc.VFM(**{
            # defaults
            **{"order": 1 if tff else 0, "field": 2, "mode": 0},
            # user configuration
            **dict(vfm_cfg),
            # required
            **{"clip": self.clip}
        })
        # prepare qtgmc
        qtgmc = havsfunc.QTGMC(**{
            # defaults
            **{
                "FPSDivisor": 2,
                "Preset": "Placebo",
                "MatchPreset": "Placebo",
                "MatchPreset2": "Placebo",
                "TFF": tff,
                "InputType": 0,
                "SourceMatch": 3,
                "Lossless": 2,
                "Sharpness": 0.2,
                "ShutterBlur": 0,
                "ShutterAngleSrc": 0,
                "ShutterAngleOut": 0,
                "SBlurLimit": 0
            },
            # user configuration
            **dict(qtgmc_cfg),
            # required
            **{
                # If QTGMC will produce anything other than Single-rate frame rate (e.g. FPSDivisor=1)
                # then vfm will desync from QTGMC as vfm returns Single-rate frame rate. We use VFM's
                # clip otherwise to lower the amount of time's QTGMC needs to run as VFM will take care
                # of the frames/fields it can first.
                "Input": vfm if "FPSDivisor" not in qtgmc_cfg or qtgmc_cfg["FPSDivisor"] == 2 else self.clip
            }
        })
        # calculate when VFM/QTGMC is needed
        # todo ; On the FieldBased == 0 line inside the first functools.partial, if it returns it's else, then it gets very very slow due
        # to it using a all of the memory available in `cores` max memory cache pool. This is causing terrible slowdowns. It seems to be
        # related to QTGMC specifically as it only occurs if the else is returning `qtgmc` or the second FrameEval. No idea why this is
        # happening :(
        self.clip = core.std.FrameEval(
            format_clip,
            functools.partial(
                lambda n, f, og: (
                    core.text.Text(og, "Untouched Frame (_FieldBased=0)", alignment=1) if self.debug else og
                ) if f.props["_FieldBased"] == 0 and ("FPSDivisor" not in qtgmc_cfg or qtgmc_cfg["FPSDivisor"] == 2) else core.std.FrameEval(
                    # calculate whether to use qtgmc or vfm
                    format_clip,
                    functools.partial(
                        lambda n, f: (
                            core.text.Text(qtgmc, f"Deinterlaced Frame (via QTGMC) [tff={tff}]", alignment=1) if self.debug else qtgmc
                        ) if self.standard == "PAL" or ("FPSDivisor" in qtgmc_cfg and qtgmc_cfg["FPSDivisor"] != 2) or f.props["_Combed"] > 0 else (
                            core.text.Text(vfm, "Matched Frame (via VFM match)", alignment=1) if self.debug else vfm
                        )
                    ),
                    prop_src=vfm
                ),
                og=self.clip
            ),
            prop_src=self.clip
        )
