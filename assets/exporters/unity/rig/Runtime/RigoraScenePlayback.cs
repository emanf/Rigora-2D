using System;
using System.Collections.Generic;
using UnityEngine;

[Serializable] public class RigoraCameraSample
{
    public string id, background, lens;
    public float[] matrix;
    public float width, height;
}
[Serializable] public class RigoraParticleSample
{
    public string owner, color, shape;
    public float[] matrix;
    public float opacity;
}
[Serializable] public class RigoraSceneSample
{
    public RigoraCameraSample camera;
    public RigoraParticleSample[] particles;
    public string[] render_order;
}

/// <summary>Samples exported scene framing and batches particles without owning game cameras.</summary>
public class RigoraScenePlayback : MonoBehaviour
{
    public bool useSceneCamera = true;
    public Material overlayMaterial, particleMaterial;
    public Camera sceneCamera { get; private set; }
    private RigoraRig rig;
    private RigoraDefinition data;
    private Batch background, lens;
    private readonly Dictionary<string, Batch> particles = new Dictionary<string, Batch>();
    private readonly Dictionary<string, List<Renderer>> parts = new Dictionary<string, List<Renderer>>();

    private sealed class Batch
    {
        public GameObject node;
        public Mesh mesh;
        public MeshRenderer renderer;
        public readonly List<Vector3> vertices = new List<Vector3>();
        public readonly List<Color> colors = new List<Color>();
        public readonly List<int> triangles = new List<int>();

        public void Clear() { vertices.Clear(); colors.Clear(); triangles.Clear(); }
        public void Upload()
        {
            renderer.enabled = vertices.Count > 0;
            mesh.Clear();
            mesh.SetVertices(vertices);
            mesh.SetColors(colors);
            mesh.SetTriangles(triangles, 0);
            mesh.RecalculateBounds();
        }
    }

    /// <summary>Bind one imported rig; resources are instance-owned and created only once.</summary>
    public void Initialize(RigoraRig owner, RigoraDefinition definition)
    {
        rig = owner;
        data = definition;
        parts.Clear();
        for (int i = 0; i < data.parts.Length; i++)
        {
            string id = data.parts[i].object_id;
            if (string.IsNullOrEmpty(id)) continue;
            if (!parts.ContainsKey(id)) parts[id] = new List<Renderer>();
            parts[id].Add(rig.partRenderers[i]);
        }
        if (sceneCamera) return;
        var node = new GameObject("Rigora scene camera");
        node.transform.SetParent(transform, false);
        sceneCamera = node.AddComponent<Camera>();
        sceneCamera.orthographic = true;
        sceneCamera.clearFlags = CameraClearFlags.SolidColor;
        sceneCamera.backgroundColor = Color.clear;
        sceneCamera.nearClipPlane = 0.01f;
        sceneCamera.farClipPlane = 1000;
        sceneCamera.useOcclusionCulling = false;
        background = CreateBatch("Rigora background", overlayMaterial);
        lens = CreateBatch("Rigora lens", overlayMaterial);
        background.renderer.sortingOrder = -30000;
        lens.renderer.sortingOrder = 30000;
    }

    /// <summary>Refresh one sampled frame, preserving game-owned cameras when opted out.</summary>
    public void ApplyFrame(int frame)
    {
        if (data.scene_samples == null || data.scene_samples.Length == 0) return;
        var sample = data.scene_samples[Mathf.Clamp(frame, 0, data.scene_samples.Length - 1)];
        bool cameraActive = useSceneCamera && sample.camera != null;
        sceneCamera.enabled = cameraActive;
        background.renderer.enabled = lens.renderer.enabled = false;
        if (cameraActive)
        {
            var camera = sample.camera;
            Matrix4x4 placement = Converted(camera.matrix);
            float w = camera.width / 100, h = camera.height / 100;
            sceneCamera.transform.position = transform.TransformPoint(placement.MultiplyPoint3x4(new Vector3(w / 2, -h / 2, -10)));
            // An explicit affine view preserves parent shear as well as camera roll/zoom.
            sceneCamera.worldToCameraMatrix = Matrix4x4.TRS(new Vector3(-w / 2, h / 2, -10), Quaternion.identity, new Vector3(1, 1, -1)) * placement.inverse * transform.worldToLocalMatrix;
            sceneCamera.projectionMatrix = Matrix4x4.Ortho(-w / 2, w / 2, -h / 2, h / 2, 0.01f, 1000);
            sceneCamera.cullingMatrix = sceneCamera.projectionMatrix * sceneCamera.worldToCameraMatrix;
            float screenAspect = sceneCamera.targetTexture ? (float)sceneCamera.targetTexture.width / sceneCamera.targetTexture.height : (float)Math.Max(1, Screen.width) / Math.Max(1, Screen.height);
            float fit = (w / h) / screenAspect;
            sceneCamera.rect = fit < 1 ? new Rect((1 - fit) / 2, 0, fit, 1) : new Rect(0, (1 - 1 / fit) / 2, 1, 1 / fit);
            Overlay(background, camera.background, placement, w, h);
            Overlay(lens, camera.lens, placement, w, h);
        }
        foreach (var batch in particles.Values) batch.Clear();
        foreach (var particle in sample.particles)
        {
            if (!particles.TryGetValue(particle.owner, out var batch))
            {
                batch = CreateBatch("Rigora particles " + particle.owner, particleMaterial);
                particles[particle.owner] = batch;
            }
            AddParticle(batch, particle);
        }
        foreach (var batch in particles.Values) batch.Upload();
        int order = 0;
        foreach (string id in sample.render_order)
        {
            if (particles.TryGetValue(id, out var batch)) batch.renderer.sortingOrder = order++;
            if (parts.TryGetValue(id, out var renderers))
                foreach (var renderer in renderers) renderer.sortingOrder = order++;
        }
    }

    private Batch CreateBatch(string name, Material template)
    {
        if (!template) throw new InvalidOperationException("Import the Rigora scene materials with RigoraRigImporter.");
        var batch = new Batch { node = new GameObject(name), mesh = new Mesh { name = name, indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 } };
        batch.mesh.MarkDynamic();
        batch.node.transform.SetParent(transform, false);
        batch.node.layer = gameObject.layer;
        batch.node.AddComponent<MeshFilter>().sharedMesh = batch.mesh;
        batch.renderer = batch.node.AddComponent<MeshRenderer>();
        batch.renderer.sharedMaterial = new Material(template);
        batch.renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        batch.renderer.receiveShadows = false;
        return batch;
    }

    private static Matrix4x4 Converted(float[] source)
    {
        var matrix = Matrix4x4.identity;
        matrix.m00 = source[0]; matrix.m10 = -source[1];
        matrix.m01 = -source[2]; matrix.m11 = source[3];
        matrix.m03 = source[4] / 100; matrix.m13 = -source[5] / 100;
        return matrix;
    }

    private void Overlay(Batch batch, string path, Matrix4x4 matrix, float width, float height)
    {
        var texture = rig.Texture(path);
        batch.renderer.enabled = texture;
        if (!texture) return;
        batch.renderer.sharedMaterial.mainTexture = texture;
        batch.mesh.vertices = new[] { matrix.MultiplyPoint3x4(Vector3.zero), matrix.MultiplyPoint3x4(new Vector3(width, 0)), matrix.MultiplyPoint3x4(new Vector3(width, -height)), matrix.MultiplyPoint3x4(new Vector3(0, -height)) };
        batch.mesh.uv = new[] { new Vector2(0, 1), new Vector2(1, 1), new Vector2(1, 0), new Vector2(0, 0) };
        batch.mesh.triangles = new[] { 0, 1, 2, 0, 2, 3 };
        batch.mesh.RecalculateBounds();
    }

    private static void AddParticle(Batch batch, RigoraParticleSample particle)
    {
        ColorUtility.TryParseHtmlString(particle.color, out var color);
        color.a *= particle.opacity;
        Matrix4x4 matrix = Converted(particle.matrix);
        int start = batch.vertices.Count;
        int sides = particle.shape == "square" ? 4 : 32;
        batch.vertices.Add(matrix.MultiplyPoint3x4(Vector3.zero));
        batch.colors.Add(color);
        for (int i = 0; i < sides; i++)
        {
            float angle = (float)i / sides * Mathf.PI * 2;
            // Source particle matrices map a unit disk or the square [-1,1]^2.
            var point = sides == 4 ? new Vector3(i == 0 || i == 3 ? -1 : 1, i < 2 ? 1 : -1) : new Vector3(Mathf.Cos(angle), -Mathf.Sin(angle));
            batch.vertices.Add(matrix.MultiplyPoint3x4(point / 100));
            batch.colors.Add(color);
            batch.triangles.Add(start);
            batch.triangles.Add(start + i + 1);
            batch.triangles.Add(start + (i + 1) % sides + 1);
        }
    }

    void OnDestroy()
    {
        foreach (var batch in particles.Values) Dispose(batch);
        Dispose(background);
        Dispose(lens);
        if (sceneCamera) Release(sceneCamera.gameObject);
    }

    private static void Dispose(Batch batch)
    {
        if (batch == null) return;
        if (batch.renderer) Release(batch.renderer.sharedMaterial);
        Release(batch.mesh);
        Release(batch.node);
    }

    private static void Release(UnityEngine.Object value)
    {
        if (!value) return;
        if (Application.isPlaying) Destroy(value);
        else DestroyImmediate(value);
    }
}
