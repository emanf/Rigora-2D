# Jump trajectory reference

`jump.json` contains 33 samples each from `Jump_Full_Short` and `Jump_Full_Long`
in Kay Lousberg's CC0 KayKit Adventurers pack. Exact source URL, pinned revision
and digest are embedded in the JSON; the author's notice is in `LICENSE.txt`.

Source: https://github.com/KayKit-Game-Assets/KayKit-Character-Pack-Adventures-1.0

Rigora retains normalized side-plane hip/ankle trajectories and foot angles.
Small endpoint drift is reconciled to neutral, legs are retargeted with fixed
lengths, and arms are authored separately. Jump, Hop and High jump use different
height/timing treatments. No source model, texture, artwork or runtime executable
is included. The offline converter is `tools/extract_run_reference.py`; see the
neighboring run reference notice for the pinned input and invocation.
