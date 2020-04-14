# std vs
from vapoursynth import core  # this may give a linter error, ignore
# std py
import os
import functools
import subprocess
# vs func repos
import havsfunc
# pip packages
from pymediainfo import MediaInfo
from pyd2v import D2V


class PDeint:

    def __init__(self, file_path, dgindex_path):
        """
        Loads video with core.d2v.Source if its MPEG-1 or MPEG-2
        otherwise it uses core.ffms2.Source.

        It extracts video streams and generates D2V files if needed.
        Also adds in a few props that may come in handy to the user.
        """
        self.file_path = file_path
        self.dgindex_path = dgindex_path
        # remove leading file:// from file_path
        if self.file_path.lower().startswith("file://"):
            self.file_path = self.file_path[7:]
            if os.name == "nt":
                # windows sometimes adds an extra leading /, usually when using an external drive
                self.file_path = self.file_path.lstrip('/')
        # get file type
        self.file_type = None
        # check if file is a DGIndexProjectFile (d2v)
        with open(self.file_path, mode="rb") as f:
            if f.read(18) == bytes([0x44, 0x47, 0x49, 0x6E, 0x64, 0x65, 0x78, 0x50, 0x72, 0x6F, 0x6A, 0x65, 0x63, 0x74, 0x46, 0x69, 0x6C, 0x65]):
                if f.read(2) != bytes([0x31, 0x36]):
                    raise ValueError("D2V was created with an unsupported indexer, please use DGIndex v1.5.8")
                self.file_type = "core.d2v.Source"
        # check if file is an mp4 or mkv
        if not self.file_type:
            if os.path.splitext(self.file_path)[-1][1:].lower() in ["mp4", "mkv"]:
                # prepare a codec ID for video
                self.mediainfo = [t for t in MediaInfo.parse(
                    filename=self.file_path
                ).tracks if t.track_type == "Video"][0]
                codec_id = self.mediainfo.codec_id or self.mediainfo.commercial_name
                if codec_id in ["MPEG-2 Video", "V_MPEG2", "MPEG-1 Video", "V_MPEG1"]:
                    # generate a d2v for this video file
                    self.file_path = self.generate_d2v(self.file_path)
                    self.file_type = "core.d2v.Source"
                else:
                    self.file_type = "core.ffms2.Source"
            else:
                raise ValueError(f"Unsupported file type ({self.file_type}). Currently only support containers MP4 and MKV.")
        # load file as clip
        if self.file_type == "core.d2v.Source":
            self.clip = core.d2v.Source(input=self.file_path, rff=False)
        elif self.file_type == "core.ffms2.Source":
            self.clip = core.ffms2.Source(source=self.file_path, alpha=False)
        else:
            raise ValueError(f"Unsupposed file type ({self.file_type})")
        # Set various exports as props
        self.standard = self.detect_standard()
        self.clip = core.std.SetFrameProp(self.clip, prop="_Sourcer", data=self.file_type)
        self.clip = core.std.SetFrameProp(self.clip, prop="_Filepath", data=self.file_path)
        self.clip = core.std.SetFrameProp(self.clip, prop="_Standard", data=self.standard)

    def generate_d2v(self, video_file):
        """Extract video files and generate a D2V for it"""
        # if the file path isn't a d2v, force it to be
        d2v_path = f"{os.path.splitext(video_file)[0]}.d2v"
        if os.path.exists(d2v_path):
            print("Skipping generation as a D2V file already exists")
            return d2v_path
        mpg_path = f"{os.path.splitext(d2v_path)[0]}.mpg"
        if os.path.exists(mpg_path):
            print("Skipping extraction of raw mpeg stream as it already exists")
        else:
            try:
                subprocess.run([
                    "mkvextract", os.path.basename(self.file_path),
                    "tracks", f"0:{os.path.basename(mpg_path)}"
                ], cwd=os.path.dirname(self.file_path))
            except FileNotFoundError:
                raise RuntimeError(
                    "PDeint: Required binary 'mkvextract' not found. "
                    "Install MKVToolNix and make sure it's binaries are in the environment path."
                )
        try:
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
        except FileNotFoundError:
            raise RuntimeError(
                "PDeint: Required binary 'DGIndex' not found.\n"
                "Windows: Download DGIndex and place the folder into 'C:/Program Files (x86)/DGIndex' (manually create folder). "
                "Once done, add that path to System Environment Variables, run a google search for instructions.\n"
                "Linux: Put the path to DGIndex.exe in the dgindex_path argument. Python Subprocess doesnt follow bash's PATH or alias, "
                "so specifying path manually will have to be done."
            )
        return d2v_path
    
    def detect_standard(self):
        """Detect standard based on frame rate"""
        if self.clip.fps.numerator == 25 and self.clip.fps.denominator == 1:
            return "PAL"
        if self.clip.fps.numerator == 30000 and self.clip.fps.denominator == 1001:
            return "NTSC"
        if self.clip.fps.numerator == 24 and self.clip.fps.denominator == 1:
            return "FILM"
        return f"{self.clip.fps}"
    
    def _deinterlace_d2v(self, kernel, kernel_clip_key, kernel_cfg, debug):
        """
        Very accurate deinterlacing using raw frame metadata to know what to
        deinterlace when necessary. It even fixes the frame rates of progressive
        streams and converts VFR to CFR when necessary.

        For MPEG2, this is as good as it gets in terms of using a deinterlacer.
        """
        # Get D2V object
        self.d2v = D2V(self.file_path)
        # Get every frames' flag data, this contains information on displaying frames
        flags = [f for l in [x["flags"] for x in self.d2v.data] for f in l]
        # Get percentage of progressive frames
        progressive_percent = (sum(1 for x in flags if x["progressive_frame"]) / len(flags))*100
        # Get pulldown information
        pulldown_frames = [n for n,f in enumerate(flags) if f["progressive_frame"] and f["rff"] and f["tff"]]
        # todo ; get an mpeg2 that uses Pulldown metadata (rff flags) that ISN'T Pulldown 2:3 to test math
        #        this math seems pretty far fetched, if we can somehow obtain the Pulldown x:x:...
        #        string that mediainfo can get, then calculating it can be much easier and more efficient.
        pulldown_cycle = [n for n,x in enumerate(flags) if not x["tff"] and not x["rff"]]
        pulldown_cycle = list(zip(pulldown_cycle[::2], pulldown_cycle[1::2]))
        pulldown_cycle = [r - l for l,r in pulldown_cycle]
        if pulldown_cycle.count(pulldown_cycle[0]) != len(pulldown_cycle):
            raise Exception(f"Unable to determine pulldown cycle as it is non linear. {pulldown_cycle}")
        pulldown_cycle = pulldown_cycle[0] + 1

        if progressive_percent != 100.0:
            # video is not all progressive content, meaning it is either:
            # - entirely interlaced
            # - mix of progressive and interlaced sections
            # interlaced sections fps == 30000/1001
            # progressive sections fps <= 30000/1001 (or == if they used Pulldown 1:1 for some reason)
            # 1. fix the frame rate of the progressive sections by applying it's pulldown (without interlacing) to make the video CFR
            #    if this isn't done, then the frame rate of the progressive sections will be 30000/1001 but the content itself will not be
            if pulldown_frames:
                self.clip = core.std.DuplicateFrames(clip=self.clip, frames=pulldown_frames)
            # 2. also apply this frame rate fix to the flag list so that each flag can be properly accessed by index
            pulldown_flags = []
            for flag in flags:
                pulldown_flags.append(flag)
                if flag["progressive_frame"] and flag["rff"] and flag["tff"]:
                    pulldown_flags.append({"progressive_frame": True, "rff": False, "tff": False})
            # 3. create a clip from the output of the kernel deinterlacer
            deinterlaced_clip = kernel(**kernel_cfg, **{kernel_clip_key: self.clip})
            double_rate = self.clip.fps.numerator * 2 == deinterlaced_clip.fps.numerator
            # 4. create a format clip, used for metadata of final clip
            format_clip = core.std.BlankClip(
                clip=self.clip,
                length=len(pulldown_flags) * (2 if double_rate else 1),
                fpsnum=self.clip.fps.numerator * (2 if double_rate else 1),
                fpsden=self.clip.fps.denominator
            )
            # 5. deinterlace whats interlaced
            def _d(n, f, c, d, fl, dr):
                if fl[int(n / 2) if dr else n]["progressive_frame"]:
                    # progressive frame, we don't need to do any deinterlacing to this frame
                    # though we may need to duplicate it if double-rate fps output
                    rc = core.std.Interleave([c, c]) if dr else c
                    return core.text.Text(rc, "\n\n\n\n\n (Untouched Frame) ", alignment=7) if debug else rc
                # interlaced frame, we need to use `d` (deinterlaced) frame.
                return core.text.Text(d, "\n\n\n\n\n ! Deinterlaced Frame ! ", alignment=7) if debug else d
            self.clip = core.std.FrameEval(
                format_clip,
                functools.partial(
                    _d,
                    c=self.clip,
                    d=deinterlaced_clip,
                    fl=pulldown_flags,
                    dr=double_rate
                ),
                prop_src=self.clip
            )
        else:
            # video is entirely progressive without a hint of interlacing in sight
            # however, it needs it's FPS to be fixed. rff=False with core.d2v.Source
            # resulted in it returning with the FPS set to 30000/1001, let's revert that
            # back to whatever it should be based on its pulldown cycle
            if pulldown_cycle:
                self.clip = core.std.AssumeFPS(
                    self.clip,
                    fpsnum=self.clip.fps.numerator - (self.clip.fps.numerator / pulldown_cycle),
                    fpsden=self.clip.fps.denominator
                )
        
        if debug:
            self.clip = core.text.Text(
                self.clip,
                " " + (" \n ".join([
                    f"{os.path.basename(self.file_path)}",
                    f"{self.standard}, Loaded with {self.file_type}",
                    f"- {len(flags)} coded pictures, which {progressive_percent:.2f}% of are Progressive",
                    f"- {len(pulldown_frames)} frames are asking for pulldown which occurs every {pulldown_cycle} frames",
                    f"- {len(flags) + len(pulldown_frames)} total frames after pulldown flags are honored"
                ])) + " ",
                alignment=7
            )
    
    def _deinterlace_ffms2(self, kernel, kernel_clip_key, kernel_cfg, debug):
        """
        Deinterlace using ffms2 (ffmpeg) using a basic FieldBased!=0 => QTGMC method
        """
        self.clip = core.std.FrameEval(
            self.clip,
            functools.partial(
                lambda n, f, c, d: (
                    core.text.Text(c, "Untouched Frame (_FieldBased=0)", alignment=1) if debug else c
                ) if f.props["_FieldBased"] == 0 else (
                    core.text.Text(d, f"Deinterlaced Frame (via QTGMC)", alignment=1) if debug else d
                ),
                c=self.clip,
                d=kernel(**kernel_cfg, **{kernel_clip_key: self.clip})
            ),
            prop_src=self.clip
        )
    
    def deinterlace(self, tff=True, kernel=None, kernel_clip_key=None, kernel_cfg=None, debug=False):
        """Deinterlace video using best method available"""
        # set default kernel to QTGMC
        if not kernel or not kernel_clip_key:
            kernel = havsfunc.QTGMC
            kernel_clip_key = "Input"
        # if kernel is QTGMC, set it's defaults
        if kernel == havsfunc.QTGMC:
            kernel_cfg = {
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
                **dict(kernel_cfg or {})
            }
        if self.file_type == "core.d2v.Source":
            self._deinterlace_d2v(kernel, kernel_clip_key, kernel_cfg, debug)
        elif self.file_type == "core.ffms2.Source":
            if kernel == havsfunc.QTGMC:
                kernel_cfg["FPSDivisor"] = 2  # ffms2 cannot handle anything other than same-rate fps
            self._deinterlace_ffms2(kernel, kernel_clip_key, kernel_cfg, debug)
        else:
            raise ValueError(f"Unimplemented deinterlacer for Sourcer {self.file_type}")
