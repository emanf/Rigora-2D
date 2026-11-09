using System;
using System.IO;
using UnityEditor;
using UnityEngine;

[Serializable] public class ExpectedPart { public string name; public Vector3[] vertices; }
[Serializable] public class ExpectedFrame { public ExpectedPart[] parts; }
[Serializable] public class ExpectedRig { public ExpectedFrame[] frames; }

public static class RigoraEditableValidation
{
    public static void RunAll()
    {
        Run();
        RunWeighted();
    }

    public static void Run()
    {
        Validate("EditableRig");
    }

    public static void RunWeighted()
    {
        Validate("EditableWeighted");
    }

    private static void Validate(string folder)
    {
        string source = Application.dataPath + "/" + folder;
        string output = RigoraRigImporter.ImportFolder(source);
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(output + "/Character.prefab");
        var root = UnityEngine.Object.Instantiate(prefab);
        try
        {
            var rig = root.GetComponent<RigoraRig>();
            rig.Initialize();
            var data = JsonUtility.FromJson<RigoraDefinition>(rig.definition.text);
            var expected = JsonUtility.FromJson<ExpectedRig>(File.ReadAllText(source + "/expected.json"));
            if (rig.partRenderers.Length != data.parts.Length) throw new Exception("Missing parts");
            if (Math.Abs(rig.motion.clip.length - 3.0 / 24) > 0.001) throw new Exception("Wrong duration");
            if (folder == "EditableWeighted" && !Array.Exists(data.parts, p =>
                Array.Exists(p.weights, w => w.values[1] > 0) && p.corrections.Length > 0))
                throw new Exception("Weighted fixture needs blended bones and mesh corrections");
            for (int p = 0; p < data.parts.Length; p++)
            {
                var mesh = (rig.partRenderers[p] as SkinnedMeshRenderer).sharedMesh;
                if (mesh.triangles.Length != data.parts[p].triangles.Length)
                    throw new Exception("Duplicated faces would double alpha blending");
                for (int i = 0; i < mesh.uv.Length; i++)
                    if (Mathf.Abs(mesh.uv[i].y - (1 - data.parts[p].uv[i].y)) > 0.0001f)
                        throw new Exception("Unity texture orientation is inverted");
            }
            for (int f = 0; f < 3; f++)
            {
                rig.Seek(f / 24.0f);
                foreach (var bone in data.nodes)
                {
                    var transform = Array.Find(root.GetComponentsInChildren<Transform>(), t => t.name == bone.name);
                    var expectedPosition = bone.samples[f].translation;
                    if (Vector3.Distance(transform.localPosition, new Vector3(expectedPosition[0], expectedPosition[1], expectedPosition[2])) > 0.0001)
                        throw new Exception("Bone animation sample differs: " + bone.label + " " + transform.localPosition + " expected " + expectedPosition[0] + "," + expectedPosition[1]);
                }
                foreach (var part in expected.frames[f].parts)
                {
                    var renderer = Array.Find(rig.partRenderers, r => r.name == part.name) as SkinnedMeshRenderer;
                    if (renderer == null || renderer.bones.Length == 0) throw new Exception("Missing weighted mesh");
                    var baked = new Mesh();
                    renderer.BakeMesh(baked);
                    var vertices = baked.vertices;
                    for (int i = 0; i < vertices.Length; i++)
                    {
                        var point = renderer.transform.TransformPoint(vertices[i]);
                        if (Vector2.Distance(point, part.vertices[i]) > 0.0002)
                            throw new Exception("Native skin vertex differs: " + part.name + " frame " + f + " vertex " + i + " " + point + " expected " + part.vertices[i]);
                    }
                    UnityEngine.Object.DestroyImmediate(baked);
                }
            }
            if (data.wardrobes.Length > 0)
            {
                var group = data.wardrobes[0];
                if (!rig.SetClothing(group.id)) throw new Exception("Wardrobe change failed");
                foreach (var variant in group.variants)
                    foreach (var part in variant.parts)
                        if (Array.Find(rig.partRenderers, r => r.name == part).enabled)
                            throw new Exception("Removed clothing remains visible");
            }
            if (!rig.SetPartColor(data.parts[0].node, Color.red)) throw new Exception("Color failed");
            rig.Seek(0);
            if (rig.partRenderers[0].sharedMaterial.color.g > 0.01f) throw new Exception("Wrong independent color");
            File.WriteAllText(Application.dataPath + "/../" + folder + "-validation.txt", "RIGORA_EDITABLE_UNITY_VALIDATED: weighted vertices, editable bones, clothing, colors, animation");
            Debug.Log("RIGORA_EDITABLE_UNITY_VALIDATED");
        }
        finally { UnityEngine.Object.DestroyImmediate(root); }
    }
}
