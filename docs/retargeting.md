# Motion retargeting (Prompt 13)

Open **Animation → Retarget motion**. Choose a source clip and source/target
skeletons. The source can be the current project or another local `.rigora`
project; opening it here does not replace the target tab.

Human, Quadruped, Winged and Flexible spine profiles suggest unique role/name
matches. Every source row can be skipped or mapped explicitly. Missing matches
are reported. Rotation offset and gain correct rest angles and mirrored motion.
Preview builds an isolated clip; scrub the slider to inspect the result. Create
clip publishes one undoable change, leaving source data and target rest geometry
intact. Edit the resulting scalar keys in the normal dope sheet.

Motion time is preserved in seconds across frame rates. Root translation scales
with mapped bone lengths; child translation uses parent proportions. Evaluated
source poses include constraints. Baked target controls bypass constraints only
inside the new clip, preventing a second IK/spring pass. Unmapped controls retain
their target rest data and ordinary constraints. This is anatomical FK transfer,
not automatic contact solving or foot planting; correct mappings and keys when
the characters differ substantially.

Sampling retains endpoints, integer source frames and authored subframes, bounded
to 10,000 source frames / 100,000 bone samples. Exported `.rigaction` files retain
and remap the baked-control list. Core tests cover timing, proportions,
corrections, missing/locked mappings, save/undo and constraint isolation; the
desktop regression exercises preview and publication through the mapping table.
