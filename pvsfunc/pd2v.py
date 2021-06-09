import functools
import math
from collections import Counter
from typing import List, Optional, Tuple, Callable

import vapoursynth as vs
from pyd2v import D2V
from vapoursynth import core

from pvsfunc.helpers import group_by_int, list_select_every, get_d2v


class PD2V:
    """
    Apply operations related to DGIndex and it's indexer file format D2V.
    All methods can be directly chained after each other, e.g. `PD2V(...).ceil().deinterlace(...)`.
    """

    def __init__(self, file: str, verbose=False):
        """
        Load a file using core.d2v.Source, prepare source for optimal use.

        It automatically creates a D2V if `file` is not a d2v, or a d2v is not next to the input
        file.

        A lot of class variables are available to be used, like flags, pulldown, d2v data.
        """
        self.file = get_d2v(file)
        self.d2v = D2V(self.file)
        self.flags = self._get_flags(self.d2v)
        self.pulldown, self.pulldown_str = self._get_pulldown(self.flags)
        self.vfr = any(f["progressive_frame"] and f["rff"] and f["tff"] for f in self.flags) and any(
            not f["progressive_frame"] for f in self.flags)
        self.clip = core.d2v.Source(self.file, rff=False)
        self.clip = self._stamp_frames(self.clip, self.flags)

        if verbose:
            coded_f = len(self.flags)
            progressive_f = sum(f["progressive_frame"] for f in self.flags)
            progressive_p = (progressive_f / coded_f) * 100
            standard = {
                0: "?",
                24 / 1: "FILM",
                25 / 1: "PAL",
                50 / 1: "PALi",
                30000 / 1001: "NTSC",
                60000 / 1001: "NTSCi",
                24000 / 1001: "NTSC (FILM)"
            }[self.clip.fps.numerator / self.clip.fps.denominator]
            self.clip = core.text.Text(
                self.clip,
                text=" " + (" \n ".join([
                    f"Progressive: {progressive_p:05.2f}% ({progressive_f})" + (
                        f" w/ Pulldown {self.pulldown_str} (Cycle: {self.pulldown})" if self.pulldown else
                        " - No Pulldown"
                    ),
                    f"Interlaced:  {100 - progressive_p:05.2f}% ({coded_f - progressive_f})",
                    f"VFR? {progressive_f > 0}",
                    standard
                ])) + " ",
                alignment=1,
                scale=1
            )

    def deinterlace(self, kernel: Callable, fps_divisor=2, verbose=False):
        """
        Deinterlace clip using specified kernel in an optimal way.

        Kernel:
        - Should be a callable function, with the first argument being the clip.
        - The function needs an argument named `TFF` or `tff` for specifying field order.
        - You can use functools.partial to specify arguments to the kernel to be used.
        - Field order should never be specified manually, unless you really really need to.

        <!> If the source is VFR, it's recommended to use ceil() or floor() before-hand unless you wish
                to keep the source as VFR.
            It assumes the `flags` data is still up to date and correct to the `clip` data. Do not
                mess with the clip data manually after sending it to this class unless you also
                update the changes on the flags. For an example of this see ceil() and floor().
        """
        if not callable(kernel):
            raise ValueError("Invalid kernel, must be a callable")

        def _d(n, f, c):
            # frame marked as progressive in flags by D2V, skip deinterlacing
            if f.props["PVSFlagProgressiveFrame"]:
                return core.text.Text(c, "Progressive", alignment=3) if verbose else c
            # interlaced frame, deinterlace (if _FieldBased is > 0)
            rc = {0: c, 1: kernel(c, TFF=False), 2: kernel(c, TFF=True)}[f.props["_FieldBased"]]
            field_order = {0: "Progressive", 1: "BFF", 2: "TFF"}[f.props["_FieldBased"]]
            return core.text.Text(rc, "Deinterlaced (%s)" % field_order, alignment=3) if verbose else rc

        self.clip = core.std.FrameEval(
            core.std.BlankClip(
                self.clip,
                length=len(self.clip) * 2 / fps_divisor,
                fpsnum=self.clip.fps.numerator * 2 / fps_divisor
            ),
            functools.partial(_d, c=self.clip),
            prop_src=self.clip
        )
        return self

    def ceil(self):
        """
        VFR to CFR by applying RFF to progressive frames without interlacing.
        This is done by duplicating the progressive frames with the RFF flag instead of interlacing them.

        <!> It may or may not actually duplicate anything. If there's no progressive frames with an RFF
                flag found, then there's no progressive frames needing to be duplicated. If this happens,
                it will simply do nothing.
            If you expect no duplicate frames caused by VFR->CFR, then use floor() instead (read warnings
                first however).
        """
        if not self.vfr:
            return self

        def _ceil(n, f, c):
            rc = core.std.SetFrameProp(c, intval=0, prop="PVSFlagRff")
            if f.props["PVSFlagProgressiveFrame"] and f.props["PVSFlagRff"] and f.props["PVSFlagTff"]:
                return [rc, rc]
            return rc

        pf = [i for i, f in enumerate(self.flags) if f["progressive_frame"] and f["rff"] and f["tff"]]
        self.clip = core.std.FrameEval(
            core.std.BlankClip(
                clip=self.clip,
                length=len(self.clip) + len(pf),
            ),
            functools.partial(_ceil, c=self.clip),
            prop_src=self.clip
        )
        self.flags = [
            x
            for i, f in enumerate(self.flags)
            for x in [dict(f, rff=False)] * (2 if i in pf else 1)
        ]
        self.vfr = False
        return self

    def floor(self, cycle: int = None, offsets: List[int] = None):
        """
        VFR to CFR by decimating interlaced sections to match progressive sections.

        Parameters:
            cycle: Defaults to pulldown cycle.
            offsets: Defaults to last frame of each cycle.

        <!> This should only be used on sources with a clean VFR. If there's any progressively burned
                frames, then it may result in an incorrect playback frame rate (even though it will
                be correctly floored). Simply make sure the Playback Duration is correct (to the point!).
            Since it's decimating frames, please understand what is being decimated in your source.
                It could be un-important (like duplicate frames) or it could be real data. This is common
                when the project was edited at 30FPS (or alike) and the content is 24FPS (or alike).
                Meaning stuff like fade-ins and outs, pans, zooms, credit sequences, general vfx, could
                all be 30FPS while the core content is only 24FPS. This happens often. Notable examples
                are, Pokemon, Family Guy and a lot of Anime.
            If you expect no duplicate frames caused by VFR->CFR, then use ceil() instead (read warnings
                first however).
            It may or may not actually decimate anything. If you have not specified a cycle, and there's
                no cycle found, then there's no progressive sections to decimate to. If this happens, it
                will simply do nothing.
        """
        cycle = cycle or self.pulldown
        if cycle:
            offsets = offsets
            if offsets is None:
                offsets = list(range(cycle - 1))
            if not offsets or len(offsets) >= cycle:
                raise ValueError("Invalid offsets, cannot be empty or have >= items of cycle")

            if not self.vfr:
                self.clip = core.std.SelectEvery(self.clip, cycle, offsets)
                return self

            wanted_fps_num = self.clip.fps.numerator - (self.clip.fps.numerator / cycle)

            progressive_frames = group_by_int([n for n, f in enumerate(self.flags) if f["progressive_frame"]])
            interlaced_frames = group_by_int([n for n, f in enumerate(self.flags) if not f["progressive_frame"]])

            self.clip = core.std.Splice([x for _, x in sorted(
                [
                    # progressive sections:
                    (
                        x[0],  # first frame # of the section, used for sorting when splicing
                        core.std.AssumeFPS(
                            self.clip[x[0]:x[-1] + 1],
                            fpsnum=wanted_fps_num,
                            fpsden=self.clip.fps.denominator
                        )
                    ) for x in progressive_frames
                ] + [
                    # interlaced sections:
                    (
                        x[0],
                        core.std.SelectEvery(
                            self.clip[x[0]:x[-1] + 1],
                            cycle,
                            offsets
                        )
                    ) for x in interlaced_frames
                ],
                key=lambda section: int(section[0])
            )])
            interlaced_frames = [
                n
                for s in interlaced_frames
                for n in list_select_every(s, cycle, offsets, inverse=True)
            ]
            self.flags = [f for i, f in enumerate(self.flags) if i not in interlaced_frames]
            self.vfr = False
        return self

    @staticmethod
    def _stamp_frames(clip: vs.VideoNode, flags: List[dict]) -> vs.VideoNode:
        """Stamp frames with prop data that may be needed."""

        def _set_flag_props(n, f, c, fl):
            for key, value in fl[n].items():
                if isinstance(value, bool):
                    value = 1 if value else 0
                if isinstance(value, bytes):
                    value = value.decode("utf-8")
                c = core.std.SetFrameProp(c, **{
                    ("intval" if isinstance(value, int) else "data"): value
                }, prop="PVSFlag%s" % key.title().replace("_", ""))
            return c[n]

        vob_indexes = [v for _, v in {f["vob"]: n for n, f in enumerate(flags)}.items()]
        vob_indexes = [
            "%s-%s" % ((0 if n == 0 else (vob_indexes[n - 1] + 1)), i)
            for n, i in enumerate(vob_indexes)
        ]
        clip = core.std.SetFrameProp(clip, prop="PVSVobIdIndexes", data=" ".join(vob_indexes))

        return core.std.FrameEval(
            clip,
            functools.partial(
                _set_flag_props,
                c=clip,
                fl=flags
            ),
            prop_src=clip
        )

    @staticmethod
    def _get_flags(d2v: D2V) -> List[dict]:
        """Get Flag Data from D2V object."""
        return [
            dict(**flag, vob=d["vob"], cell=d["cell"])
            for d in d2v.data
            for flag in d["flags"]
        ]

    @staticmethod
    def _get_pulldown(flags: List[dict]) -> Tuple[int, Optional[str]]:
        """
        Get commonly used Pulldown syntax string and cycle.
        Returns None if Pulldown is not used, tuple (pulldown, cycle) otherwise.
        """
        rff = [n for n, f in enumerate(flags) if f["rff"]][::2]
        if len(rff) <= 1:
            return 0, None
        cycle = Counter([
            right - left for left, right
            in zip(rff[::2], rff[1::2])
        ]).most_common(1)[0][0] + 1
        pulldown = ["2"] * math.floor(cycle / 2)
        if cycle % 2:
            pulldown.pop()
            pulldown.append("3")
        return cycle, ":".join(pulldown)
