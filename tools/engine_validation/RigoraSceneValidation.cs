using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

/// <summary>Runs real Editor geometry, texture, callback and scene tests without a UI.</summary>
public static class RigoraSceneValidation
{
    public static void Render()
    {
        string output = RigoraRigImporter.ImportFolder(Application.dataPath + "/EditableWeighted");
        var root = UnityEngine.Object.Instantiate(AssetDatabase.LoadAssetAtPath<GameObject>(output + "/Character.prefab"));
        var target = new RenderTexture(256, 144, 24, RenderTextureFormat.ARGB32);
        var image = new Texture2D(256, 144, TextureFormat.RGBA32, false);
        var previous = RenderTexture.active;
        try
        {
            var rig = root.GetComponent<RigoraRig>();
            rig.Initialize();
            rig.scenePlayback.sceneCamera.targetTexture = target;
            rig.Seek(1.0f / 24);
            target.Create();
            rig.scenePlayback.sceneCamera.Render();
            RenderTexture.active = target;
            image.ReadPixels(new Rect(0, 0, 256, 144), 0, 0);
            image.Apply();
            foreach (var color in image.GetPixels32())
                Require(color.a >= 254, "Translucent overlays must preserve the opaque background alpha");
            File.WriteAllBytes(Application.dataPath + "/../rendered-scene.png", image.EncodeToPNG());
            Debug.Log("RIGORA_UNITY_SCENE_RENDERED");
        }
        finally
        {
            RenderTexture.active = previous;
            target.Release();
            UnityEngine.Object.DestroyImmediate(image);
            UnityEngine.Object.DestroyImmediate(target);
            UnityEngine.Object.DestroyImmediate(root);
        }
    }

    public static void Run()
    {
        RigoraEditableValidation.RunAll();
        string output = RigoraRigImporter.ImportFolder(Application.dataPath + "/EditableWeighted");
        var root = UnityEngine.Object.Instantiate(AssetDatabase.LoadAssetAtPath<GameObject>(output + "/Character.prefab"));
        try
        {
            var rig = root.GetComponent<RigoraRig>();
            rig.Initialize();
            var definition = JsonUtility.FromJson<RigoraDefinition>(rig.definition.text);
            var events = new List<RigoraEvent>();
            rig.EventFired += events.Add;
            rig.Advance(0);
            Require(events.Count == 1 && events[0].name == "Start", "Initial frame event must fire exactly once");
            rig.Advance(0);
            Require(events.Count == 1, "Held time must not duplicate an event");
            rig.Advance(2.0f / 24);
            Require(events.Count == 3 && events[1].type == "footstep" && events[1].payload_json.Contains("stone"), "Retimed callbacks/payloads are missing");
            rig.Seek(0);
            Require(events.Count == 3, "Seek must remain silent");
            var firstTexture = rig.partRenderers[0].sharedMaterial.mainTexture;
            rig.Seek(2.0f / 24);
            Require(firstTexture != rig.partRenderers[0].sharedMaterial.mainTexture, "Animated vector colors must switch real textures");
            Require(rig.partRenderers[0].sharedMaterial.mainTexture.name.EndsWith("-1"), "Alternate texture was not imported");
            var scene = rig.scenePlayback;
            Require(scene && scene.sceneCamera && scene.sceneCamera.enabled, "Exported scene camera is missing");
            root.transform.position = new Vector3(3, 2, 0);
            root.transform.rotation = Quaternion.Euler(0, 0, 23);
            root.transform.localScale = new Vector3(1.2f, 0.8f, 1);
            for (int frame = 0; frame < 3; frame++)
            {
                rig.Seek(frame / 24.0f);
                var camera = definition.scene_samples[frame].camera;
                float x = camera.width * 0.27f, y = camera.height * 0.63f;
                float[] m = camera.matrix;
                var local = new Vector3((m[0] * x + m[2] * y + m[4]) / 100, -(m[1] * x + m[3] * y + m[5]) / 100, 0);
                var viewport = scene.sceneCamera.WorldToViewportPoint(root.transform.TransformPoint(local));
                Require(Vector2.Distance(viewport, new Vector2(0.27f, 0.37f)) < 0.0001f, "Sampled camera affine projection/cut differs from Rigora");
            }
            Require(definition.scene_samples[0].camera.id != definition.scene_samples[1].camera.id, "Fixture needs an actual camera cut");
            Require(!string.IsNullOrEmpty(definition.scene_samples[1].camera.background) && !string.IsNullOrEmpty(definition.scene_samples[1].camera.lens), "Fixture needs background/lens images");
            rig.Seek(1.0f / 24);
            var backdrop = root.transform.Find("Rigora background").GetComponent<MeshRenderer>();
            var lens = root.transform.Find("Rigora lens").GetComponent<MeshRenderer>();
            Require(backdrop.enabled && lens.enabled && backdrop.sortingOrder < lens.sortingOrder, "Scene overlays/order are missing");
            var source = definition.scene_samples[1].particles;
            Require(source.Length > 0, "Fixture needs actual particles");
            var particle = root.transform.Find("Rigora particles " + source[0].owner);
            var mesh = particle.GetComponent<MeshFilter>().sharedMesh;
            Require(mesh.vertexCount == source.Length * 33, "Particle primitives are missing or unbatched");
            Require(Vector3.Distance(mesh.vertices[0], new Vector3(source[0].matrix[4] / 100, -source[0].matrix[5] / 100, 0)) < 0.0001f, "Particle placement differs");
            Require(Vector3.Distance(mesh.vertices[1], new Vector3((source[0].matrix[4] + source[0].matrix[0]) / 100, -(source[0].matrix[5] + source[0].matrix[1]) / 100, 0)) < 0.0001f, "Particle radius must convert from source pixels to meters");
            Require(Math.Abs(mesh.colors[0].a - source[0].opacity) < 0.0001f, "Particle opacity differs");
            var gameCamera = new GameObject("Game-owned camera").AddComponent<Camera>();
            try
            {
                scene.useSceneCamera = false;
                rig.Seek(0);
                Require(!scene.sceneCamera.enabled && !backdrop.enabled && !lens.enabled && gameCamera.enabled, "Scene opt-out must preserve game camera ownership");
                Require(particle.GetComponent<MeshRenderer>().enabled, "Particles must remain visible under a game-owned camera");
            }
            finally { UnityEngine.Object.DestroyImmediate(gameCamera.gameObject); }
            rig.Seek(0);
            rig.Advance(definition.duration * 0.9f);
            int count = events.Count;
            rig.Advance(definition.duration * 0.2f);
            Require(events.Count == count + (definition.loop ? 1 : 0), "End/loop boundary callback is incorrect");
            var ownedMeshes = root.GetComponentsInChildren<MeshFilter>();
            UnityEngine.Object.DestroyImmediate(root);
            foreach (var filter in ownedMeshes) Require(!filter, "Scene resources were orphaned on destroy");
            string result = "RIGORA_UNITY_SCENE_VALIDATED: native weighted vertices, wardrobe, independent colors, animated textures, typed callbacks, affine camera cuts, lens/background, batched particles, camera opt-out and instance cleanup";
            File.WriteAllText(Application.dataPath + "/../scene-validation.txt", result);
            Debug.Log(result);
        }
        finally { if (root) UnityEngine.Object.DestroyImmediate(root); }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }
}
