"""Offline plugin project generation and three original working SDK examples."""

import json
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from rigora.domain.content import ContentItem, ContentPack
from rigora.domain.entities import Bone, Skeleton, Transform
from rigora.infrastructure.content_packs import write_pack
from rigora.sdk.api import API_VERSION, PluginManifest


def generate_plugin(
    destination: Path, plugin_id: str, kind: Literal["tool", "deformer", "content"] = "tool"
) -> Path:
    """Create a reviewable distribution while preserving any existing project directory."""
    if destination.exists():
        raise FileExistsError(f"Plugin project already exists: {destination}")
    module = "rigora_" + plugin_id.replace(".", "_")
    capability = {"tool": "tools", "deformer": "deformers", "content": "asset_packs"}[kind]
    permissions = {
        "tool": ("project.read", "project.write", "ui"),
        "deformer": ("project.read",),
        "content": ("filesystem",),
    }[kind]
    manifest = PluginManifest(
        id=plugin_id,
        name=f"Example {kind}",
        description=f"Original Rigora API {API_VERSION} {kind} example.",
        version="1.0.0",
        author="Rigora SDK examples",
        api_version=API_VERSION,
        entry_point=f"{module}:register",
        capabilities=(capability,),
        permissions=permissions,
        resources=("starter.rigpack",) if kind == "content" else (),
        license="CC0-1.0",
    )
    package = destination / module
    package.mkdir(parents=True)
    (package / "rigora-plugin.json").write_text(
        json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    if kind == "tool":
        source = '''"""Original pointer-driven stamp using the public viewport-tool contract."""

from rigora.sdk import PluginContext, PluginRequest
from rigora.application_services.rigging import RigService
from rigora.engine.sampling import number


def stamp(request: PluginRequest):
    """Create one undoable bone at the pressed scene coordinate; other pointer phases are inert."""
    if request.arguments.get("phase") != "press":
        return None
    x, y = number(request.arguments["x"]), number(request.arguments["y"])
    key = RigService(request.require_document()).create_bone((x, y), (x + 100, y + 20))
    return {"bone_id": key}


def register(context: PluginContext) -> None:
    """Register an original bone-stamp tool with a bundled Material glyph."""
    context.action(context.manifest.id + ".stamp", "Stamp a bone", stamp, tool=True,
                   placements=("menu:Rig/Custom tools", "toolbar:Custom tools", "context:scene"),
                   icon="device_hub")
'''
    elif kind == "deformer":
        source = '''"""Original sine displacement operating on immutable geometric engine inputs."""

import math
from rigora.sdk import PluginContext
from rigora.engine.deformation import DeformationContext


def wave(context: DeformationContext):
    """Return a fresh local-space mesh with a finite, animatable vertical sine displacement."""
    amount = context.scalar("amount", 12)
    return tuple((x, y + math.sin(x / 40) * amount) for x, y in context.points)


def register(context: PluginContext) -> None:
    """Publish the geometric solver and its numeric parameter defaults."""
    context.register("deformers", context.manifest.id + ".wave", "Sine wave", wave,
                     parameters={"amount": 12.0}, icon="waves",
                     placements=("menu:Deform/Plugin deformers",))
'''
    else:
        source = '''"""Original data-only skeleton pack registered through the public SDK."""

from rigora.sdk import PluginContext, PluginRequest


def register(context: PluginContext) -> None:
    """Expose a declared pack resource to the normal offline content browser."""
    def pack(request: PluginRequest):
        """Resolve the original bundled pack without changing a project or copying files."""
        return context.resource("starter.rigpack")
    context.register("asset_packs", context.manifest.id + ".starter", "Three-joint starter", pack)
'''
        create_content(package / "starter.rigpack", plugin_id)
    (package / "__init__.py").write_text(source, encoding="utf-8")
    (destination / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling==1.32.4"]\nbuild-backend = "hatchling.build"\n\n'
        f'[project]\nname = "{module.replace("_", "-")}"\nversion = "1.0.0"\n'
        'requires-python = ">=3.12"\ndependencies = []\n\n'
        f'[project.entry-points."rigora.plugins"]\n"{plugin_id}" = "{module}:register"\n\n'
        f'[tool.hatch.build.targets.wheel]\npackages = ["{module}"]\n',
        encoding="utf-8",
    )
    (destination / "README.md").write_text(
        f"# {manifest.name}\n\nOpen `{module}/rigora-plugin.json` in Rigora's plugin manager "
        "to add the source directory. Review the manifest and source, then explicitly trust "
        "and enable it. Registration runs only after trust.\n\n"
        "For package installation, build this project and install its wheel into the same "
        "Python environment as Rigora. Refresh plugin discovery afterward.\n\n"
        "Python plugins are executable code. Manifest permissions describe intended access; "
        "they are not a security sandbox. Use only trusted code.\n\n"
        "Original generated example code and content: CC0-1.0.\n",
        encoding="utf-8",
    )
    return package


def create_content(destination: Path, plugin_id: str) -> None:
    """Generate an original three-bone rig and semantic metadata in a portable pack."""

    def key(name: str) -> str:
        """Derive stable content identities independently of runtime template instances."""
        return str(uuid5(NAMESPACE_URL, f"{plugin_id}:{name}"))

    bones = tuple(
        Bone(
            id=key(f"bone{i}"),
            name=f"spine.{i}",
            length=90,
            parent_id=key(f"bone{i - 1}") if i else None,
            transform=Transform(x=90 if i else 300, y=0 if i else 250),
        )
        for i in range(3)
    )
    skeleton = Skeleton(
        name="Three-joint original",
        bones=bones,
        extra={"anatomy": "chain", "semantic_mapping": {b.name: b.id for b in bones}},
    )
    item = ContentItem(
        id=key("item"),
        name=skeleton.name,
        kind="rig",
        category="Skeleton templates",
        author="Rigora SDK examples",
        license="CC0-1.0",
        payload={"skeleton": skeleton.to_dict()},
    )
    pack = ContentPack(
        id=key("pack"),
        name="Original SDK content example",
        author=item.author,
        license=item.license,
        items=(item,),
    )
    write_pack(destination, pack, {})
