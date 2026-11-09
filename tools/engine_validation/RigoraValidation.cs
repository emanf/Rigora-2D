using System;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class RigoraValidation
{
    public static void Run()
    {
        string root = RigoraSpriteImporter.ImportFolder(Application.dataPath + "/Rigora");
        var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(root + "/Animation.anim");
        if (clip == null || clip.frameRate != 12 || Math.Abs(clip.length - 0.25) > 0.001)
            throw new Exception("Wrong clip duration or FPS");
        var binding = AnimationUtility.GetObjectReferenceCurveBindings(clip)[0];
        var keys = AnimationUtility.GetObjectReferenceCurve(clip, binding);
        if (keys.Length != 3 || keys[0].value == keys[1].value)
            throw new Exception("Missing or unordered sprite keys");
        var sprite = (Sprite)keys[0].value;
        if (sprite.pivot != new Vector2(32, 0)) throw new Exception("Wrong pivot");
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(root + "/Character.prefab");
        if (prefab == null || prefab.GetComponent<Animator>() == null)
            throw new Exception("Missing playable prefab");
        File.WriteAllText(Application.dataPath + "/../rigora-validation.txt", "RIGORA_UNITY_VALIDATED: native sprite clip, duration, keys, pivot, prefab");
        Debug.Log("RIGORA_UNITY_VALIDATED");
    }
}
