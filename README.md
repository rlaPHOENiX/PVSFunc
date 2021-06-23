# pvsfunc

pvsfunc (PHOENiX's VapourSynth Functions) is my compilation of VapourSynth Scripts, Functions, and Helpers.

[![Build Tests](https://img.shields.io/github/workflow/status/rlaPHOENiX/pvsfunc/Version%20test?label=Python%203.6%2B%20builds)](https://github.com/rlaPHOENiX/pvsfunc/actions?query=workflow%3A%22Version+test%22)
[![License](https://img.shields.io/github/license/rlaPHOENiX/pvsfunc?style=flat)](https://github.com/rlaPHOENiX/pvsfunc/blob/master/LICENSE)
[![DeepSource](https://deepsource.io/gh/rlaPHOENiX/pvsfunc.svg/?label=active+issues&show_trend=true)](https://deepsource.io/gh/rlaPHOENiX/pvsfunc/?ref=repository-badge)
[![Issues](https://img.shields.io/github/issues/rlaPHOENiX/pvsfunc?style=flat)](https://github.com/rlaPHOENiX/pvsfunc/issues)
[![PR's Accepted](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat)](https://makeapullrequest.com)

## Installation

Install VapourSynth C libraries first! (this is different to the pypi/pip `vapoursynth` package!)

    pip install --user pvsfunc

Done! However, there are further dependencies listed below that you may need to install depending on the classes you
intend to use, and your use-case. Don't forget to install them if needed!

## Building

Building from source requires [Poetry](https://python-poetry.org).  
Simply run `poetry install` or `poetry build` for distribution wheel and source packages.

## License

This project is released under the GNU GENERAL PUBLIC LICENSE Version 3 (GPLv3) license.
Please read and agree to the license before use, it can be found in the [LICENSE](LICENSE) file.

* * *

Below is information about the projects included in pvsfunc that are available to use. Don't take it as full
documentation as that is being worked on.

## PD2V

Convenience class for working with DGIndex D2V project files (MPEG-1/2 videos). Includes source loading, frame
matching, deinterlacing, and more.

### Example Usage

```py
from pvsfunc import PD2V
from functools import partial
from havsfunc import QTGMC

clip = PD2V(r"C:\Users\john\Videos\s01e01.d2v", verbose=True).\
    ceil().\
    deinterlace(
        kernel=partial(QTGMC, FPSDivisor=2, Preset="Very Slow"),
        verbose=True
    ).\
    clip

# ... any manual changes to clip

clip.set_output()
```

The above example will load a D2V project file located at `C:\Users\john\Videos\s01e01.d2v` in Verbose mode.
Verbose mode will display extra information during the PD2V use.

It then runs `ceil()` which frame-matches the progressive sections of the video with the interlaced sections by
duplicating the progressive frames (instead of interlacing).

It then deinterlaces the interlaced sections of the video with QTGMC as the kernel. The Kernel must have a `tff` or
`TFF` argument to be compatible, but the field order should not be manually set by the user.

Finally, it takes the clip and set's it for VapourSynth output.

### Dependencies

- [d2vsource] (core.d2v) VapourSynth plugin
- [DGIndex] v1.5.8 or newer
- [mkvextract] Only required if you plan on providing non demuxed streams (e.g., mp4, mkv)

To install [d2vsource] it's as simple as `vsrepo install d2vsource` on Windows. Other Operating System user's know the
drill, go check your package repository's or compile it yourself.

Make sure [DGIndex] and [mkvextract] is available on your environment path and has execution permissions. Note Linux
Users: Add to system profile path, not terminal/rc path. DGIndex is Windows-only but is supported if you install Wine.

## PLS

Convenience class for working with L-SMASH-WORKS LWI project files. Includes source loading and deinterlacing.
More features are to be implemented in the future once a Python-based LWI project parser is available.

Refer to PD2Vs example usage as it's very similar to how PLS is used.

### Dependencies

- [lsmash] (core.lsmas) VapourSynth plugin
- [mkvmerge] Only required if input file has a container-set frame rate that differs to the encoded frame rate

To install [lsmash] it's as simple as `vsrepo install lsmas` on Windows. Other Operating System user's know the drill,
go check your package repository's or compile it yourself.

Make sure [mkvmerge] is available on your environment path and has execution permissions. Note Linux Users: Add to
system profile path, not terminal/rc path.

## PDebox

Lightweight class to apply de-boxing based on an output aspect-ratio. Similar scripts would annoyingly want you to
just crop in yourself which is incredibly annoying.

## PDecimate

Decimate (delete) frames in a specified pattern using cycle and offsets. This is typically used for Inverse-Telecine
purposes.

## PKernel

Kernel storage class for any custom Deinterlacing kernels I'm working on or tinkering with that you may want to use.
Just know that they are most likely not the type of deinterlacing you may expect, as it's generally a playground for
looking into strange tactics of deinterlacing.

### VoidWeave

VoidWeave is a deinterlacing method involving in-painting with machine-learning.

It takes footage and separates the weaved fields so that each field is full-height with the missing data of the field
being 255 RGB green instead of empty/black. The in-painting machine-learning system would then in-paint the missing
data wherever it finds the 255 RGB Green pixels. It works quite well as YUV 4:2:0 DVD data doesn't seem to ever reach
255 green though it does get close, but never quite 255.

I tested it on a Live Action DVD and the results were honestly outstanding! The time it took to run the in-painting
was about the same as QTGMC on Very Slow, with similar results! I think where this method may really shine is with
Cartoon/Animated sources as QTGMC does not do them well.

It all still requires a lot more testing, but it looks like it could be a really nice method! Especially now that I've
learned Disney has also been working on it around the same tim, back in 2020 :P

* * *

## Documentation

### OUT OF DATE! To be updated soon.

| Class                                           | Import                              |
| ----------------------------------------------- | ----------------------------------- |
| [PSourcer](#psourcer-psourcerpy)                | `from pvsfunc import PSourcer`      |
| [PDeinterlacer](#pdeinterlacer-pdeinterlacerpy) | `from pvsfunc import PDeinterlacer` |
| [PDecimate](#pdecimate-pdecimatepy)             | `from pvsfunc import PDecimate`     |
| [PDebox](#pdebox-pdeboxpy)                      | `from pvsfunc import PDebox`        |

### PDeinterlacer ([pdeinterlacer.py](/pvsfunc/pdeinterlacer.py))

PDeinterlacer (class) is a convenience wrapper for deinterlacing clips. Its unique feature is it can handle variable scan-type videos and therefore variable frame-rate videos as well. It will always return a progressive and CFR (constant frame-rate) video. It's similar to a retail DVD player as it deinterlaces only if the frame is marked as interlaced, no metrics or guessing is involved.

Just to clarify this is a deinterlacer wrapper, not it's own deinterlacer kernel. You must supply it with a kernel to use. To reduce dependencies, no base kernel is defaulted.

`from pvsfunc import PDeinterlacer`  
`PDeinterlacer(clip, func kernel[, dict kernel_args=None, bool debug=False])`

- clip: Clip to deinterlace, this must be a clip loaded with PSourcer as it requires some of the props that PSourcer applies to clips.
- kernel: Deinterlacer Kernel Function to use for deinterlacing. If you don't know which kernel to use, [QTGMC](http://avisynth.nl/index.php/QTGMC) is a good bet but may not be the answer for your specific source. For example, QTGMC isn't the best for Animated sources, or sources that have consistent amount of duplicate frames (e.g. animation).
- kernel_args: Arguments to pass to the Kernel Function when deinterlacing.
- debug: Debug Mode, Enable it if you want to debug frame information.

### PDecimate ([pdecimate.py](/pvsfunc/pdecimate.py))

PDecimate (class) is a convenience wrapper for Decimating operations. It can be used to delete frames in a variable or constant pattern, either by manual definition or by automated means (via VDecimate however, <https://git.io/avoid-tdecimate>). Decimation is often used for IVTC purposes to remove constant pattern pulldown frames (duplicate frames for changing frame rate).

`from pvsfunc import PDecimate`  
`PDecimate(clip, int cycle, list<int> offsets[, per_vob_id=True, mode=0, debug=False])`

- clip: Clip to decimate, this must be a clip loaded with PSourcer as it requires some of the props that PSourcer applies to clips.
- cycle: Defines the amount of frames to calculate offsets on at a time.
- offset: Mode 0's offsets are a zero-indexed list. This indicates which frames to KEEP from the cycle. Set to `None` when using mode=1.
- per_vob_id: When Clip is a DVD-Video Object (.VOB): Reset the cycle every time the VOB Cell changes.
- mode: 0=core.std.SelectEvery (recommended), 1=core.vivtc.VDecimate (be warned; its inaccurate!)
- debug: Skip decimation and print debugging information. Useful to check if the frames that the cycle and offset settings you have provided are correct and actually decimate the right frames.

### PDebox ([pdebox.py](/pvsfunc/pdebox.py))

PDebox (class) is a convenience wrapper for Deboxing operations. Ever encounter sources where there's black bars on the top and bottom, sides, or both? That means it's Letterboxed, Pillarboxed, or Windowboxed respectively. PDebox helps you remove Letterboxing and Pillarboxing, and through that Windowboxing too.

`from pvsfunc import PDebox`  
`PDebox(clip, str aspect_ratio, [int mode=0, offset=0])`

- clip: Clip to debox.
- aspect_ratio: Aspect Ratio you wish to crop to, in string form, e.g. `"4:3"`.
- mode: Mode of operation, 0=Pillarboxing, 1=Letterboxing.
- offset: If the boxing is slightly more on one side than the other, than you can set this offset appropriately to move the area that PDebox returns. e.g. mode=0, and there's 1px more of a pillar on the right than on the left, the offset should be -1.

  [dg]: http://rationalqm.us/dgmpgdec/dgmpgdec.html
  [mkvnix]: https://mkvtoolnix.download
  [lsmash]: https://github.com/VFR-maniac/L-SMASH-Works
  [d2vs]: https://github.com/dwbuiten/d2vsource
