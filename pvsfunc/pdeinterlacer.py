# std vs
from vapoursynth import core
import vapoursynth as vs
import os
import functools
# vs func repos
try:
    import havsfunc
except ImportError:
    raise RuntimeError(
        "pvsfunc.PDeinterlacer: Required script havsfunc not found. "
        "https://github.com/HomeOfVapourSynthEvolution/havsfunc"
    )

# pip packages
from pyd2v import D2V


class PDeinterlacer:
    """
    PDeinterlacer (PHOENiX Deinterlacer)
    Deinterlaces a clip with the most optimal wrapping based on the sourcer.
    The clip will need to be loaded from PSourcer to work as it needs it's Props.
    """

    def __init__(self, clip, tff=True, kernel=None, kernel_args=None, debug=False):
        self.clip = clip
        self.tff = tff
        self.kernel = kernel
        self.kernel_args = kernel_args
        self.debug = debug
        # validate arguments
        if not isinstance(self.clip, vs.VideoNode):
            raise TypeError("pvsfunc.PDeinterlacer: This is not a clip")
        # set default kernel to QTGMC
        if not self.kernel:
            self.kernel = havsfunc.QTGMC
        # if kernel is QTGMC, set it's defaults
        if self.kernel == havsfunc.QTGMC:
            self.kernel_args = {
                # defaults
                **{
                    "FPSDivisor": 2,
                    "Preset": "Placebo",
                    "MatchPreset": "Placebo",
                    "MatchPreset2": "Placebo",
                    "TFF": self.tff,
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
                **dict(self.kernel_args or {})
            }
        self.props = self.clip.get_frame(0).props
        self.props = {k: v.decode("utf-8") if type(v) == bytes else v for k, v in self.props.items()}
        if self.props["PVSSourcer"] == "core.d2v.Source":
            self._d2v()
        elif self.props["PVSSourcer"] == "core.ffms2.Source":
            if kernel == havsfunc.QTGMC:
                kernel_args["FPSDivisor"] = 2  # only supporting same-rate fps atm
            self._ffms2()
        elif self.props["PVSSourcer"] == "core.imwri.Read":
            print("pvsfunc.PDeinterlacer: Warning: This source is a clip of images and cannot be deinterlaced.")
        else:
            raise ValueError(f"Unimplemented deinterlacer for Sourcer {self.props['PVSSourcer']}")
    
    def _d2v(self):
        """
        Very accurate deinterlacing using raw frame metadata to know what to
        deinterlace when necessary. It even fixes the frame rates of progressive
        streams and converts VFR to CFR when necessary.

        For MPEG2, this is as good as it gets in terms of using a deinterlacer.
        """
        # Get D2V object
        self.d2v = D2V(self.props["PVSFilePath"])
        # Get every frames' flag data, this contains information on displaying frames
        flags = [[dict(**y, vob=x["vob"], cell=x["cell"]) for y in x["flags"]] for x in self.d2v.data]
        flags = [f for l in flags for f in l]
        # Get percentage of progressive frames
        progressive_percent = (sum(1 for x in flags if x["progressive_frame"]) / len(flags))*100
        # Get pulldown information
        pulldown_frames = [n for n,f in enumerate(flags) if f["progressive_frame"] and f["rff"] and f["tff"]]
        # todo ; get an mpeg2 that uses Pulldown metadata (rff flags) that ISN'T Pulldown 2:3 to test math
        #        this math seems pretty far fetched, if we can somehow obtain the Pulldown x:x:...
        #        string that mediainfo can get, then calculating it can be much easier and more efficient.
        pulldown_cycle = [n for n,f in enumerate(flags) if f["tff"] and f["rff"]]
        if pulldown_cycle:
            pulldown_cycle = list(zip(pulldown_cycle[::2], pulldown_cycle[1::2]))
            pulldown_cycle = [r - l for l,r in pulldown_cycle]
            pulldown_cycle = max(set(pulldown_cycle), key=pulldown_cycle.count) + 1  # most common entry + 1
        else:
            pulldown_cycle = None

        if progressive_percent != 100.0:
            # video is not all progressive content, meaning it is either:
            # - entirely interlaced
            # - mix of progressive and interlaced sections
            # 1. fix the frame rate of the progressive sections by applying it's pulldown (without interlacing)
            if pulldown_frames:
                self.clip = core.std.DuplicateFrames(clip=self.clip, frames=pulldown_frames)
            # 2. also fix the frame rate of the flag list to match the fixed clip
            pulldown_flags = []
            for flag in flags:
                pulldown_flags.append(flag)
                if flag["progressive_frame"] and flag["rff"] and flag["tff"]:
                    pulldown_flags.append(
                        dict(**{**flag, **{"progressive_frame": True, "rff": False, "tff": False}})
                    )
            # 3. create a clip from the output of the kernel deinterlacer
            deinterlaced_clip = self.kernel(self.clip, **self.kernel_args)
            fps_factor = (deinterlaced_clip.fps.numerator / deinterlaced_clip.fps.denominator)
            fps_factor = fps_factor / (self.clip.fps.numerator / self.clip.fps.denominator)
            if fps_factor != 1.0 and fps_factor != 2.0:
                raise ValueError(
                    f"pvsfunc.PDeinterlacer: The deinterlacer kernel returned an unsupported frame-rate ({deinterlaced_clip.fps}). "
                    "Only single-rate and double-rate is supported with PDeinterlacer at the moment."
                )
            # 4. create a format clip, used for metadata of final clip
            format_clip = core.std.BlankClip(
                clip=deinterlaced_clip,
                length=len(pulldown_flags) * fps_factor
            )
            # 5. deinterlace whats interlaced
            def _d(n, f, c, d, fl, ff):
                flag = fl[int(n / ff)]
                if flag["progressive_frame"]:
                    # progressive frame, we don't need to do any deinterlacing to this frame
                    # though we may need to duplicate it if double-rate fps output
                    rc = core.std.Interleave([c] * ff) if ff > 1 else c
                    return core.text.Text(
                        rc,
                        f"\n\n\n\n\n\n VOB: {flag['vob']}/{flag['cell']} - Frame #{n} - Untouched ",
                        alignment=7
                    ) if self.debug else rc
                # interlaced frame, we need to use `d` (deinterlaced) frame.
                return core.text.Text(
                    d,
                    f"\n\n\n\n\n\n VOB: {flag['vob']}/{flag['cell']} - Frame #{n} - Deinterlaced! ",
                    alignment=7
                ) if self.debug else d
            self.clip = core.std.FrameEval(
                format_clip,
                functools.partial(
                    _d,
                    c=self.clip,
                    d=deinterlaced_clip,
                    fl=pulldown_flags,
                    ff=fps_factor
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
        
        if self.debug:
            fps = self.clip.fps
            if self.clip.fps.numerator == 25:
                fps = "PAL"
            elif self.clip.fps.numerator == 30000:
                fps = "NTSC"
            elif self.clip.fps.numerator == 24:
                fps = "FILM"
            self.clip = core.text.Text(
                self.clip,
                " " + (" \n ".join([
                    f"{os.path.basename(self.props['PVSFilePath'])}",
                    f"{fps}, Loaded with {self.props['PVSSourcer']}",
                    f"- {len(flags)} coded pictures, which {progressive_percent:.2f}% of are Progressive",
                    f"- {len(pulldown_frames)} frames are asking for pulldown{f' which occurs every {pulldown_cycle} frames' if pulldown_cycle else ''}",
                    f"- {len(flags) + len(pulldown_frames)} total frames after pulldown flags are honored"
                ])) + " ",
                alignment=7
            )
    
    def _ffms2(self):
        """
        Deinterlace using ffms2 (ffmpeg) using a basic FieldBased!=0 => QTGMC method
        """
        self.clip = core.std.FrameEval(
            self.clip,
            functools.partial(
                lambda n, f, c, d: (
                    core.text.Text(c, "Untouched Frame (_FieldBased=0)", alignment=1) if self.debug else c
                ) if f.props["_FieldBased"] == 0 else (
                    core.text.Text(d, "Deinterlaced Frame (via QTGMC)", alignment=1) if self.debug else d
                ),
                c=self.clip,
                d=self.kernel(self.clip, **self.kernel_args)
            ),
            prop_src=self.clip
        )
