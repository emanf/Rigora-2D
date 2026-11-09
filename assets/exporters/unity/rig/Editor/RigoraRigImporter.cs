using System;
using System.IO;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

/// <summary>Builds native editable skins and animations without third-party Unity packages.</summary>
public static class RigoraRigImporter
{
    [MenuItem("Tools/Rigora/Import editable rig")]
    public static void SelectFolder()
    {
        string folder = EditorUtility.OpenFolderPanel("Choose Rigora editable rig in Assets", "Assets", "");
        if (!string.IsNullOrEmpty(folder)) ImportFolder(folder);
    }

    public static string ImportFolder(string folder)
    {
        string path = FileUtil.GetProjectRelativePath(Path.GetFullPath(folder).Replace('\\', '/'));
        if (!path.StartsWith("Assets/", StringComparison.Ordinal))
            throw new InvalidOperationException("Extract the rig package inside Assets.");
        var definition = AssetDatabase.LoadAssetAtPath<TextAsset>(path + "/rig.json");
        var data = JsonUtility.FromJson<RigoraDefinition>(definition.text);
        if (data.format != "rigora.editable-rig" || data.version != 1 || data.parts.Length == 0)
            throw new InvalidDataException("Invalid Rigora editable rig.");
        string output = AssetDatabase.GenerateUniqueAssetPath(path + "/GeneratedRig");
        AssetDatabase.CreateFolder(path, Path.GetFileName(output));
        var root = new GameObject("RigoraRig");
        try
        {
            var transforms = new Transform[data.nodes.Length];
            for (int i = 0; i < transforms.Length; i++) transforms[i] = new GameObject(data.nodes[i].name).transform;
            for (int i = 0; i < transforms.Length; i++)
            {
                transforms[i].SetParent(data.nodes[i].parent < 0 ? root.transform : transforms[data.nodes[i].parent], false);
                SetTransform(transforms[i], data.nodes[i].samples[0]);
            }
            var renderers = new Renderer[data.parts.Length];
            var textures = new Dictionary<string, Texture2D>();
            var clip = new AnimationClip { name = data.clip, frameRate = data.fps, legacy = true };
            for (int n = 0; n < data.nodes.Length; n++)
            {
                string nodePath = AnimationUtility.CalculateTransformPath(transforms[n], root.transform);
                for (int channel = 0; channel < 10; channel++)
                {
                    string property = channel < 3 ? "localPosition." + "xyz"[channel] : channel < 7 ? "localRotation." + "xyzw"[channel - 3] : "localScale." + "xyz"[channel - 7];
                    var keys = new Keyframe[data.nodes[n].samples.Length + 1];
                    for (int f = 0; f < keys.Length; f++)
                    {
                        var sample = data.nodes[n].samples[Math.Min(f, keys.Length - 2)];
                        float value = channel < 3 ? sample.translation[channel] : channel < 7 ? sample.rotation[channel - 3] : sample.scale[channel - 7];
                        keys[f] = new Keyframe(f / data.fps, value);
                    }
                    SetLinearCurve(clip, nodePath, typeof(Transform), property, keys);
                }
            }
            for (int p = 0; p < data.parts.Length; p++)
            {
                var part = data.parts[p];
                var node = new GameObject(part.node);
                node.transform.SetParent(root.transform, false);
                var mesh = new Mesh { name = part.label };
                mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
                mesh.vertices = part.positions;
                var uv = new Vector2[part.uv.Length];
                for (int i = 0; i < uv.Length; i++) uv[i] = new Vector2(part.uv[i].x, 1 - part.uv[i].y);
                mesh.uv = uv;
                mesh.triangles = part.triangles;
                var bindposes = new Matrix4x4[part.bindposes.Length];
                var bones = new Transform[part.joints.Length];
                for (int i = 0; i < bindposes.Length; i++)
                {
                    for (int c = 0; c < 16; c++) bindposes[i][c] = part.bindposes[i].values[c];
                    bones[i] = transforms[part.joints[i]];
                }
                mesh.bindposes = bindposes;
                var weights = new BoneWeight[part.weights.Length];
                for (int i = 0; i < weights.Length; i++)
                {
                    var w = part.weights[i];
                    weights[i] = new BoneWeight { boneIndex0 = w.indices[0], boneIndex1 = w.indices[1], boneIndex2 = w.indices[2], boneIndex3 = w.indices[3], weight0 = w.values[0], weight1 = w.values[1], weight2 = w.values[2], weight3 = w.values[3] };
                }
                mesh.boneWeights = weights;
                for (int f = 0; f < part.corrections.Length; f++)
                {
                    string shape = "sample_" + f;
                    mesh.AddBlendShapeFrame(shape, 100, part.corrections[f].vertices, null, null);
                    var keys = new Keyframe[part.corrections.Length + 1];
                    for (int t = 0; t < keys.Length; t++) keys[t] = new Keyframe(t / data.fps, Math.Min(t, keys.Length - 2) == f ? 100 : 0);
                    SetLinearCurve(clip, part.node, typeof(SkinnedMeshRenderer), "blendShape." + shape, keys);
                }
                mesh.RecalculateBounds();
                AssetDatabase.CreateAsset(mesh, output + "/Mesh_" + p + ".asset");
                foreach (string texturePath in part.texture_states ?? new[] { part.texture })
                {
                    ImportTexture(path, texturePath, textures);
                }
                var material = new Material(Shader.Find("Rigora/Flat"));
                material.mainTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(path + "/" + part.texture);
                material.renderQueue = 3000;
                AssetDatabase.CreateAsset(material, output + "/Material_" + p + ".mat");
                var renderer = node.AddComponent<SkinnedMeshRenderer>();
                renderer.sharedMesh = mesh;
                renderer.bones = bones;
                renderer.sharedMaterial = material;
                renderer.sortingOrder = p;
                renderer.updateWhenOffscreen = true;
                renderers[p] = renderer;
            }
            clip.EnsureQuaternionContinuity();
            AssetDatabase.CreateAsset(clip, output + "/Animation.anim");
            var animation = root.AddComponent<Animation>();
            animation.cullingType = AnimationCullingType.AlwaysAnimate;
            animation.AddClip(clip, clip.name);
            animation.clip = clip;
            var controller = root.AddComponent<RigoraRig>();
            controller.definition = definition;
            controller.motion = animation;
            controller.partRenderers = renderers;
            if (data.scene_samples != null)
            {
                foreach (var sample in data.scene_samples)
                    if (sample.camera != null)
                    {
                        ImportTexture(path, sample.camera.background, textures);
                        ImportTexture(path, sample.camera.lens, textures);
                    }
                var scene = root.AddComponent<RigoraScenePlayback>();
                scene.useSceneCamera = data.use_scene_camera;
                scene.overlayMaterial = new Material(Shader.Find("Rigora/Flat"));
                scene.particleMaterial = new Material(Shader.Find("Rigora/Particles"));
                AssetDatabase.CreateAsset(scene.overlayMaterial, output + "/Overlay.mat");
                AssetDatabase.CreateAsset(scene.particleMaterial, output + "/Particles.mat");
                controller.scenePlayback = scene;
            }
            controller.texturePaths = new string[textures.Count];
            controller.textureAssets = new Texture2D[textures.Count];
            int textureIndex = 0;
            foreach (var pair in textures)
            {
                controller.texturePaths[textureIndex] = pair.Key;
                controller.textureAssets[textureIndex++] = pair.Value;
            }
            for (int i = 0; i < renderers.Length; i++) renderers[i].enabled = data.parts[i].states[0].visible;
            if (data.audio != null)
            {
                controller.voice = root.AddComponent<AudioSource>();
                controller.voice.clip = AssetDatabase.LoadAssetAtPath<AudioClip>(path + "/" + data.audio.path);
                controller.voice.playOnAwake = false;
            }
            PrefabUtility.SaveAsPrefabAsset(root, output + "/Character.prefab");
            AssetDatabase.SaveAssets();
            return output;
        }
        finally { UnityEngine.Object.DestroyImmediate(root); }
    }

    private static void ImportTexture(string folder, string path, Dictionary<string, Texture2D> textures)
    {
        if (string.IsNullOrEmpty(path) || textures.ContainsKey(path)) return;
        var importer = AssetImporter.GetAtPath(folder + "/" + path) as TextureImporter;
        if (!importer) throw new InvalidDataException("Missing texture: " + path);
        importer.textureType = TextureImporterType.Default;
        importer.alphaIsTransparency = true;
        importer.mipmapEnabled = false;
        importer.textureCompression = TextureImporterCompression.Uncompressed;
        importer.maxTextureSize = 4096;
        importer.SaveAndReimport();
        textures[path] = AssetDatabase.LoadAssetAtPath<Texture2D>(folder + "/" + path);
    }

    private static void SetTransform(Transform node, RigoraSample sample)
    {
        node.localPosition = new Vector3(sample.translation[0], sample.translation[1], sample.translation[2]);
        node.localRotation = new Quaternion(sample.rotation[0], sample.rotation[1], sample.rotation[2], sample.rotation[3]);
        node.localScale = new Vector3(sample.scale[0], sample.scale[1], sample.scale[2]);
    }

    private static void SetLinearCurve(AnimationClip clip, string path, Type type, string property, Keyframe[] keys)
    {
        var curve = new AnimationCurve(keys);
        for (int i = 0; i < keys.Length; i++)
        {
            AnimationUtility.SetKeyLeftTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
            AnimationUtility.SetKeyRightTangentMode(curve, i, AnimationUtility.TangentMode.Linear);
        }
        AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, type, property), curve);
    }
}
