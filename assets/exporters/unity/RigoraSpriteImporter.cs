// Creates native Unity animation assets from an explicitly selected Rigora sprite package.
using System;
using System.IO;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public static class RigoraSpriteImporter
{
    [Serializable] public class Frame { public string path; }
    [Serializable] public class Manifest
    {
        public string format, name;
        public int version;
        public float fps;
        public bool loop;
        public Frame[] frames;
    }

    [MenuItem("Tools/Rigora/Import sprite animation")]
    public static void ImportSelected()
    {
        string folder = EditorUtility.OpenFolderPanel("Choose Rigora package inside Assets", "Assets", "");
        if (!string.IsNullOrEmpty(folder)) ImportFolder(folder);
    }

    // Public entry point also permits unattended editor validation.
    public static string ImportFolder(string folder)
    {
        string relative = FileUtil.GetProjectRelativePath(Path.GetFullPath(folder).Replace('\\', '/'));
        if (!relative.StartsWith("Assets/", StringComparison.Ordinal))
            throw new InvalidOperationException("Extract the package inside this project's Assets folder: " + relative);
        var data = JsonUtility.FromJson<Manifest>(File.ReadAllText(Path.Combine(folder, "animation.json")));
        if (data.format != "rigora.baked-sprites" || data.version != 1 || data.frames.Length < 1 || data.fps <= 0)
            throw new InvalidDataException("Invalid Rigora sprite manifest.");
        string generated = AssetDatabase.GenerateUniqueAssetPath(relative + "/Generated");
        AssetDatabase.CreateFolder(relative, Path.GetFileName(generated));
        var keys = new ObjectReferenceKeyframe[data.frames.Length];
        for (int i = 0; i < data.frames.Length; i++)
        {
            string path = relative + "/" + data.frames[i].path;
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) throw new InvalidDataException("Missing sprite: " + path);
            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode = SpriteImportMode.Single;
            importer.spritePixelsPerUnit = 100;
            importer.alphaIsTransparency = true;
            importer.mipmapEnabled = false;
            importer.npotScale = TextureImporterNPOTScale.None;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            var settings = new TextureImporterSettings();
            importer.ReadTextureSettings(settings);
            settings.spriteAlignment = 9; // Custom pivot; all frames share the same canvas.
            settings.spritePivot = new Vector2(0.5f, 0);
            importer.SetTextureSettings(settings);
            importer.SaveAndReimport();
            var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(path);
            if (sprite == null) throw new InvalidDataException("Sprite import failed: " + path);
            keys[i] = new ObjectReferenceKeyframe { time = i / data.fps, value = sprite };
        }
        var clip = new AnimationClip { name = data.name, frameRate = data.fps };
        AnimationUtility.SetObjectReferenceCurve(clip, new EditorCurveBinding {
            path = "", type = typeof(SpriteRenderer), propertyName = "m_Sprite"
        }, keys);
        var clipSettings = AnimationUtility.GetAnimationClipSettings(clip);
        clipSettings.loopTime = data.loop;
        clipSettings.startTime = 0;
        clipSettings.stopTime = data.frames.Length / data.fps;
        AnimationUtility.SetAnimationClipSettings(clip, clipSettings);
        AssetDatabase.CreateAsset(clip, generated + "/Animation.anim");
        var controller = AnimatorController.CreateAnimatorControllerAtPath(generated + "/Animation.controller");
        controller.AddMotion(clip);
        var root = new GameObject(data.name);
        try
        {
            root.AddComponent<SpriteRenderer>().sprite = (Sprite)keys[0].value;
            root.AddComponent<Animator>().runtimeAnimatorController = controller;
            PrefabUtility.SaveAsPrefabAsset(root, generated + "/Character.prefab");
        }
        finally { UnityEngine.Object.DestroyImmediate(root); }
        AssetDatabase.SaveAssets();
        Debug.Log("Rigora sprite animation imported: " + generated);
        return generated;
    }
}
