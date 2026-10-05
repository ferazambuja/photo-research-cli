# Source attribution and licenses

## MATLAB PR driver

The serial implementation is based on a MATLAB PR-655/PR-670 driver,
adapted to Python by Fernando Voltolini de Azambuja in 2026.
Original class implementation and updates: Tucker Downs (2020–2021); earlier
serial routines and class updates: Luke Hellwig (2020, 2022).

The Python implementation retains the model verification, native-grid parsing,
paced command writes, bounded reply waits, error handling and backlight lifecycle.
It does not port the MATLAB UI, settings API, colorimetry or MAT persistence.

Original MATLAB driver license:

```text
Copyright 2021 Luke Hellwig, Tucker Downs, Minyao Li, Michael Murdoch, and
Yongmin Park. See OWNERS.txt.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

The original contributors named above are retained here in place of the
MATLAB distribution's OWNERS.txt reference.

## Psychtoolbox protocol handling

Remote-mode initialization and 50 ms character pacing follow the MATLAB
adaptation of Psychtoolbox's PR670init and PR670write routines. Native-grid
validation was informed by PR670parsespdstr. Sources at revision
`8f952b4cae7ee3fd90a792b1b36bfb3030ed701d`:

- [PR670init.m](https://github.com/Psychtoolbox-3/Psychtoolbox-3/blob/8f952b4cae7ee3fd90a792b1b36bfb3030ed701d/Psychtoolbox/PsychHardware/PR670Toolbox/PR670init.m)
- [PR670write.m](https://github.com/Psychtoolbox-3/Psychtoolbox-3/blob/8f952b4cae7ee3fd90a792b1b36bfb3030ed701d/Psychtoolbox/PsychHardware/PR670Toolbox/PR670write.m)
- [PR670parsespdstr.m](https://github.com/Psychtoolbox-3/Psychtoolbox-3/blob/8f952b4cae7ee3fd90a792b1b36bfb3030ed701d/Psychtoolbox/PsychHardware/PR670Toolbox/PR670parsespdstr.m)
- [Distribution license](https://github.com/Psychtoolbox-3/Psychtoolbox-3/blob/8f952b4cae7ee3fd90a792b1b36bfb3030ed701d/Psychtoolbox/License.txt)

Applicable MIT notice, retained from the MATLAB distribution:

```text
Copyright (c) The individual Psychtoolbox core developers:
          (c) 1996-2022, David Brainard <brainard@psych.upenn.edu>
          (c) 1996-2022, Denis Pelli    <denis.pelli@nyu.edu>
          (c) 1996-2007, Allen Ingling  <allen.ingling@nyu.edu>
          (c) 2005-2023, Mario Kleiner  <mario.kleiner.de@gmail.com>

          (c) Individual major contributors:
          (c) 2006       Richard F. Murray <rfm@yorku.ca>
          (c) 2008-2022  Diederick C. Niehorster <dcnieho@gmail.com>
          (c) 2013-2022  Ian Andolina
          (c) 2008-2011  Tobias Wolf <towolf@tuebingen.mpg.de>

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the
following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## pySerial

Runtime dependency: [pySerial 3.5](https://pyserial.readthedocs.io/), by Chris
Liechti and contributors, under its BSD license. It is installed as a dependency;
its source is not vendored into this project. See the installed distribution's
license and [upstream license](https://github.com/pyserial/pyserial/blob/v3.5/LICENSE.txt).
