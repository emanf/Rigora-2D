# Example deformer

Open `rigora_org_rigora_example_deformer/rigora-plugin.json` in Rigora's plugin manager to add the source directory. Review the manifest and source, then explicitly trust and enable it. Registration runs only after trust.

For package installation, build this project and install its wheel into the same Python environment as Rigora. Refresh plugin discovery afterward.

Python plugins are executable code. Manifest permissions describe intended access; they are not a security sandbox. Use only trusted code.

Original generated example code and content: CC0-1.0.
