using System;
using System.Collections.Generic;
using UnityEngine;

[Serializable] public class RigoraSample { public float[] translation, rotation, scale; }
[Serializable] public class RigoraNode { public string id, name, label, kind; public int parent; public RigoraSample[] samples; }
[Serializable] public class RigoraMatrix { public float[] values; }
[Serializable] public class RigoraWeights { public int[] indices; public float[] values; }
[Serializable] public class RigoraCorrection { public Vector3[] vertices; }
[Serializable] public class RigoraState { public bool visible; public float opacity; }
[Serializable] public class RigoraEvent { public string id, name, type, target, payload_json; public float seconds, frame; }
[Serializable] public class RigoraPart
{
    public string id, node, label, texture, object_id;
    public string[] texture_states;
    public Vector3[] positions;
    public Vector2[] uv;
    public int[] triangles, joints;
    public RigoraMatrix[] bindposes;
    public RigoraWeights[] weights;
    public RigoraCorrection[] corrections;
    public RigoraState[] states;
}
[Serializable] public class RigoraVariant { public string id, name; public string[] parts, occludes; }
[Serializable] public class RigoraWardrobe { public string id, name, owner, selected; public RigoraVariant[] variants; }
[Serializable] public class RigoraAudio { public string path; public float offset, duration, gain; public bool muted; }
[Serializable] public class RigoraDefinition
{
    public string format, clip;
    public int version;
    public float fps, duration;
    public bool loop;
    public bool use_scene_camera;
    public RigoraSceneSample[] scene_samples;
    public RigoraNode[] nodes;
    public RigoraPart[] parts;
    public RigoraWardrobe[] wardrobes;
    public RigoraAudio audio;
    public RigoraEvent[] events;
}

/// <summary>Controls native bone animation, per-part visibility/color and replaceable clothing.</summary>
public class RigoraRig : MonoBehaviour
{
    public TextAsset definition;
    public Animation motion;
    public Renderer[] partRenderers;
    public AudioSource voice;
    public string[] texturePaths;
    public Texture2D[] textureAssets;
    public RigoraScenePlayback scenePlayback;
    public event Action<RigoraEvent> EventFired;
    private RigoraDefinition data;
    private Material[] materials, originalMaterials;
    private readonly Dictionary<string, string> selections = new Dictionary<string, string>();
    private readonly Dictionary<string, Color> colors = new Dictionary<string, Color>();
    private readonly Dictionary<string, Texture2D> textures = new Dictionary<string, Texture2D>();
    private double eventTime;
    private bool started;

    void Awake()
    {
        Initialize();
    }

    public void Initialize()
    {
        data = JsonUtility.FromJson<RigoraDefinition>(definition.text);
        if (data.format != "rigora.editable-rig" || data.version != 1)
            throw new InvalidOperationException("Unsupported Rigora rig definition.");
        textures.Clear();
        if (texturePaths != null && textureAssets != null)
            for (int i = 0; i < Math.Min(texturePaths.Length, textureAssets.Length); i++)
                textures[texturePaths[i]] = textureAssets[i];
        eventTime = 0;
        started = false;
        if (materials == null)
        {
            materials = new Material[partRenderers.Length];
            originalMaterials = new Material[partRenderers.Length];
            for (int i = 0; i < partRenderers.Length; i++)
            {
                originalMaterials[i] = partRenderers[i].sharedMaterial;
                materials[i] = new Material(originalMaterials[i]);
                partRenderers[i].sharedMaterial = materials[i];
            }
        }
        if (Application.isPlaying && motion && motion.clip)
        {
            motion.wrapMode = data.loop ? WrapMode.Loop : WrapMode.ClampForever;
            motion.Play();
        }
        if (scenePlayback) scenePlayback.Initialize(this, data);
        ApplyState(0);
    }

    void OnDestroy()
    {
        if (materials == null) return;
        for (int i = 0; i < materials.Length; i++)
        {
            if (partRenderers[i] && partRenderers[i].sharedMaterial == materials[i])
                partRenderers[i].sharedMaterial = originalMaterials[i];
            if (Application.isPlaying) Destroy(materials[i]);
            else DestroyImmediate(materials[i]);
        }
    }

    void LateUpdate()
    {
        if (data == null) return;
        if (motion && motion.clip && motion.isPlaying)
        {
            EmitInterval(Time.deltaTime * motion[motion.clip.name].speed);
        }
        float seconds = motion && motion.clip ? motion[motion.clip.name].time : 0;
        if (data.loop && data.duration > 0) seconds %= data.duration;
        ApplyState(seconds);
    }

    /// <summary>Advance a caller-owned clock, delivering callbacks and sampling native bones.</summary>
    public void Advance(float deltaSeconds)
    {
        if (!float.IsFinite(deltaSeconds) || deltaSeconds < 0)
            throw new ArgumentOutOfRangeException(nameof(deltaSeconds));
        EmitInterval(deltaSeconds);
        float seconds = (float)(data.loop ? eventTime % data.duration : eventTime);
        Sample(seconds);
        ApplyState(seconds);
    }

    private void EmitInterval(float deltaSeconds)
    {
        double candidate = eventTime + Math.Max(0, deltaSeconds);
        double previous = started ? eventTime : -0.000001;
        started = true;
        long first = data.loop ? (long)Math.Floor(eventTime / data.duration) : 0;
        long last = data.loop ? (long)Math.Floor(candidate / data.duration) : 0;
        if (last - first > 4096)
            throw new ArgumentOutOfRangeException(nameof(deltaSeconds), "Advance at most 4096 loops per call.");
        if (data.events != null)
            for (long cycle = first; cycle <= last; cycle++)
                foreach (var item in data.events)
                {
                    double at = item.seconds + cycle * data.duration;
                    if (at > previous && at <= candidate) EventFired?.Invoke(item);
                }
        eventTime = data.loop ? candidate : Math.Min(candidate, data.duration);
    }

    internal Texture2D Texture(string path)
    {
        return !string.IsNullOrEmpty(path) && textures.TryGetValue(path, out var value) ? value : null;
    }

    public bool SetClothing(string groupId, string variantId = "")
    {
        foreach (var group in data.wardrobes)
        {
            if (group.id != groupId) continue;
            bool found = string.IsNullOrEmpty(variantId);
            foreach (var variant in group.variants) if (variant.id == variantId) found = true;
            if (!found) return false;
            selections[groupId] = variantId;
            float seconds = motion && motion.clip ? motion[motion.clip.name].time : 0;
            if (data.loop && data.duration > 0) seconds %= data.duration;
            ApplyState(seconds);
            return true;
        }
        return false;
    }

    public bool SetPartColor(string partName, Color color)
    {
        foreach (var part in data.parts)
            if (part.node == partName) { colors[partName] = color; return true; }
        return false;
    }

    public void Seek(float seconds)
    {
        if (!float.IsFinite(seconds)) throw new ArgumentOutOfRangeException(nameof(seconds));
        seconds = Mathf.Clamp(seconds, 0, data.duration);
        eventTime = seconds;
        started = true;
        Sample(seconds);
        ApplyState(seconds);
    }

    private void Sample(float seconds)
    {
        if (motion && motion.clip)
        {
            var state = motion[motion.clip.name];
            state.time = Mathf.Clamp(seconds, 0, data.duration);
            motion.clip.SampleAnimation(gameObject, state.time);
        }
    }

    private void ApplyState(float seconds)
    {
        int frame = Mathf.Clamp((int)(seconds * data.fps), 0, data.parts[0].states.Length - 1);
        var visible = new Dictionary<string, bool>();
        foreach (var part in data.parts) visible[part.node] = part.states[frame].visible;
        foreach (var group in data.wardrobes)
        {
            if (!selections.ContainsKey(group.id)) continue;
            foreach (var variant in group.variants)
            {
                foreach (string part in variant.parts) visible[part] = false;
                foreach (string part in variant.occludes) visible[part] = true;
            }
            foreach (var variant in group.variants)
                if (variant.id == selections[group.id])
                    foreach (string part in variant.parts) visible[part] = true;
        }
        var covered = new HashSet<string>();
        foreach (var group in data.wardrobes)
        {
            string selected = selections.ContainsKey(group.id) ? selections[group.id] : group.selected;
            foreach (var variant in group.variants)
                if (variant.id == selected)
                    foreach (string part in variant.occludes) covered.Add(part);
        }
        for (int i = 0; i < data.parts.Length; i++)
        {
            var part = data.parts[i];
            var renderer = partRenderers[i];
            renderer.enabled = visible[part.node] && !covered.Contains(part.node);
            Color tint = colors.ContainsKey(part.node) ? colors[part.node] : Color.white;
            tint.a *= part.states[frame].opacity;
            var material = materials[i];
            if (part.texture_states != null && textures.TryGetValue(part.texture_states[frame], out var texture))
                material.mainTexture = texture;
            if (material.HasProperty("_BaseColor")) material.SetColor("_BaseColor", tint);
            else material.color = tint;
        }
        if (scenePlayback) scenePlayback.ApplyFrame(frame);
        if (voice && voice.clip && data.audio != null)
        {
            float time = seconds + data.audio.offset;
            bool audible = motion && motion.isPlaying && !data.audio.muted && time >= 0 && time < data.audio.duration;
            voice.volume = data.audio.gain;
            if (audible)
            {
                if (!voice.isPlaying) { voice.time = time; voice.Play(); }
                else if (Mathf.Abs(voice.time - time) > 0.12f) voice.time = time;
            }
            else voice.Pause();
        }
    }
}
