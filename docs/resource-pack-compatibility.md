# Content pack compatibility

Rigora imports portable `.rigpack` packages containing a versioned manifest and
owned artwork or scene fragments. Assets, animation clips, skeletons, bindings and
deformation data stay editable after placement. Pack metadata includes attribution
and license fields; imported user content retains its existing license.

Use [Creative Templates](creative-templates.md) for supported skeleton, action,
FFD, spring and animated Object placement. Use [Linked Objects](linked-objects.md)
for reusing Objects across scenes.

Extracting textures from an archive does not recover its rig or animation.
Reference-only texture recoveries are excluded by their recovery metadata,
independent of the pack author. Other user-installed packs remain available.
No external reverse-engineering service is required by the application.
