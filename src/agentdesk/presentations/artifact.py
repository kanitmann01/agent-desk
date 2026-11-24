"""The artifact card a presentation run stores.

One builder for every stage of a run: the pack identity keys, and the
run-folder prefix on the written file paths, are written here and
nowhere else, so the fresh run, the paused research card and the
resumed write cannot drift apart.
"""

from __future__ import annotations


def deck_artifact(pack, variant: str, recipe: str, phase: str = "",
                  folder: str = "", rendered: dict | None = None, **fields) -> dict:
    """The artifact dict for one presentation run stage.

    The pack identity is written once here. A written deck passes the
    run folder and the rendered preview, so the file, pdf and image
    paths get their folder prefix in one place. Callers add whatever
    else their stage contributes (plan, sources, kept ids).
    """
    artifact = {
        "kind": "presentation",
        "templateId": pack.id,
        "templateVersion": pack.version,
        "digest": pack.digest,
        "variant": variant,
        "recipe": recipe,
    }
    if phase:
        artifact["phase"] = phase
    if rendered is not None:
        artifact["file"] = f"{folder}/deck.pptx"
        artifact["renderer"] = rendered["renderer"]
        artifact["previewNote"] = rendered["note"]
        artifact["pdf"] = f"{folder}/{rendered['pdf']}" if rendered["pdf"] else ""
        artifact["images"] = [f"{folder}/{image}" for image in rendered["images"]]
    artifact.update(fields)
    return artifact
