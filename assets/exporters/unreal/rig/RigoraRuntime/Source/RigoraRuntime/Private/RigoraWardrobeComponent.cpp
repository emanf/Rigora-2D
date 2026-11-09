#include "RigoraWardrobeComponent.h"
#include "Components/MeshComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "GameFramework/Actor.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/Texture2D.h"

namespace
{
FString Text(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key)
{
    FString Value;
    if (Object) Object->TryGetStringField(Key, Value);
    return Value;
}
TArray<TSharedPtr<FJsonValue>> Array(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key)
{
    const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
    return Object && Object->TryGetArrayField(Key, Values) ? *Values : TArray<TSharedPtr<FJsonValue>>();
}
}

URigoraWardrobeComponent::URigoraWardrobeComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
}

void URigoraWardrobeComponent::BeginPlay()
{
    Super::BeginPlay();
    SetComponentTickEnabled(InitializeRig());
}

bool URigoraWardrobeComponent::InitializeRig()
{
    if (!GetOwner() || !Definition || Definition->DefinitionJson.Len() > 128 * 1024 * 1024) return false;
    TSharedPtr<FJsonObject> Parsed;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Definition->DefinitionJson), Parsed)) return false;
    double Rate = 0, Length = 0, Version = 0;
    if (Text(Parsed, TEXT("format")) != TEXT("rigora.editable-rig") ||
        !Parsed->TryGetNumberField(TEXT("version"), Version) || Version != 1 ||
        !Parsed->TryGetNumberField(TEXT("fps"), Rate) || Rate < 1 || Rate > 240 ||
        !Parsed->TryGetNumberField(TEXT("duration"), Length) || Length <= 0) return false;
    TArray<FPart> Imported;
    for (const auto& Value : Array(Parsed, TEXT("parts")))
    {
        auto Object = Value->AsObject();
        FPart Part;
        Part.Name = Text(Object, TEXT("node"));
        if (Part.Name.IsEmpty()) return false;
        for (const auto& StateValue : Array(Object, TEXT("states")))
        {
            auto State = StateValue->AsObject();
            bool Visible = false;
            double Opacity = 0;
            if (!State || !State->TryGetBoolField(TEXT("visible"), Visible) ||
                !State->TryGetNumberField(TEXT("opacity"), Opacity)) return false;
            Part.Visible.Add(Visible);
            Part.Opacity.Add(FMath::Clamp(static_cast<float>(Opacity), 0.f, 1.f));
        }
        if (Part.Visible.IsEmpty() || Part.Visible.Num() > 600) return false;
        for (const auto& Texture : Array(Object, TEXT("texture_states")))
            Part.Textures.Add(Texture->AsString());
        if (!Part.Textures.IsEmpty() && Part.Textures.Num() != Part.Visible.Num()) return false;
        Imported.Add(MoveTemp(Part));
    }
    if (Imported.IsEmpty() || Imported.Num() > 512) return false;
    Parts = MoveTemp(Imported);
    Data = Parsed;
    FPS = Rate;
    Duration = Length;
    Parsed->TryGetBoolField(TEXT("loop"), Loop);
    Time = 0;
    EventStarted = false;
    Selections.Empty();
    TArray<UMeshComponent*> Components;
    GetOwner()->GetComponents<UMeshComponent>(Components);
    for (auto* Component : Components)
    {
        FString AssetName;
        if (auto* Skeletal = Cast<USkeletalMeshComponent>(Component))
        {
            if (Skeletal->GetSkeletalMeshAsset()) AssetName = Skeletal->GetSkeletalMeshAsset()->GetName();
        }
        else if (auto* Static = Cast<UStaticMeshComponent>(Component))
        {
            if (Static->GetStaticMesh()) AssetName = Static->GetStaticMesh()->GetName();
        }
        for (const auto& Part : Parts)
            if (Component->GetName().Contains(Part.Name) || AssetName.Contains(Part.Name))
                BindPart(Part.Name, Component);
    }
    ApplyState();
    return true;
}

bool URigoraWardrobeComponent::BindPart(const FString& PartName, UMeshComponent* Component)
{
    if (!IsValid(Component)) return false;
    for (auto& Part : Parts)
        if (Part.Name == PartName)
        {
            Part.Component = Component;
            Part.Material = Component->CreateDynamicMaterialInstance(0);
            return true;
        }
    return false;
}

bool URigoraWardrobeComponent::SetClothing(const FString& GroupId, const FString& VariantId)
{
    for (const auto& Value : Array(Data, TEXT("wardrobes")))
    {
        auto Group = Value->AsObject();
        if (Text(Group, TEXT("id")) != GroupId) continue;
        bool Found = VariantId.IsEmpty();
        for (const auto& Variant : Array(Group, TEXT("variants")))
            Found |= Text(Variant->AsObject(), TEXT("id")) == VariantId;
        if (!Found) return false;
        Selections.Add(GroupId, VariantId);
        ApplyState();
        return true;
    }
    return false;
}

bool URigoraWardrobeComponent::SetPartColor(const FString& PartName, FLinearColor Color)
{
    for (auto& Part : Parts)
        if (Part.Name == PartName) { Part.Color = Color; ApplyState(); return true; }
    return false;
}

void URigoraWardrobeComponent::Seek(float Seconds)
{
    Time = FMath::Clamp(Seconds, 0.f, Duration);
    EventStarted = true;
    ApplyState();
}

void URigoraWardrobeComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    if (Playing && Duration > 0)
    {
        const float Previous = EventStarted ? Time : -KINDA_SMALL_NUMBER;
        EventStarted = true;
        EmitEvents(Previous, Time + FMath::Max(0.f, DeltaTime));
        Time += DeltaTime;
        Time = Loop ? FMath::Fmod(Time, Duration) : FMath::Min(Time, Duration);
    }
    ApplyState();
}

void URigoraWardrobeComponent::EmitEvents(float Previous, float Candidate)
{
    if (!Data || Duration <= 0) return;
    const int32 Last = Loop ? FMath::Min(4096, FMath::FloorToInt(Candidate / Duration)) : 0;
    const auto Events = Array(Data, TEXT("events"));
    for (int32 Cycle = 0; Cycle <= Last; ++Cycle)
        for (const auto& Value : Events)
        {
            const auto Event = Value->AsObject();
            double Seconds = 0;
            if (!Event || !Event->TryGetNumberField(TEXT("seconds"), Seconds)) continue;
            const double At = Seconds + Cycle * Duration;
            if (At > Previous && At <= Candidate)
                OnAnimationEvent.Broadcast(Text(Event, TEXT("id")), Text(Event, TEXT("name")),
                    Text(Event, TEXT("type")), Text(Event, TEXT("payload_json")), Text(Event, TEXT("target")));
        }
}

void URigoraWardrobeComponent::ApplyState()
{
    if (!Data) return;
    const int32 Frame = FMath::Max(0, FMath::FloorToInt(Time * FPS));
    TMap<FString, bool> Visible;
    for (const auto& Part : Parts) Visible.Add(Part.Name, Part.Visible[FMath::Min(Frame, Part.Visible.Num() - 1)]);
    auto Groups = Array(Data, TEXT("wardrobes"));
    for (const auto& Value : Groups)
    {
        auto Group = Value->AsObject();
        auto* Selection = Selections.Find(Text(Group, TEXT("id")));
        if (!Selection) continue;
        for (const auto& VariantValue : Array(Group, TEXT("variants")))
        {
            auto Variant = VariantValue->AsObject();
            for (const auto& Part : Array(Variant, TEXT("parts"))) Visible.Add(Part->AsString(), false);
            for (const auto& Part : Array(Variant, TEXT("occludes"))) Visible.Add(Part->AsString(), true);
        }
        for (const auto& VariantValue : Array(Group, TEXT("variants")))
        {
            auto Variant = VariantValue->AsObject();
            if (Text(Variant, TEXT("id")) == *Selection)
                for (const auto& Part : Array(Variant, TEXT("parts"))) Visible.Add(Part->AsString(), true);
        }
    }
    TSet<FString> Covered;
    for (const auto& Value : Groups)
    {
        auto Group = Value->AsObject();
        FString Selected = Selections.Contains(Text(Group, TEXT("id"))) ? Selections[Text(Group, TEXT("id"))] : Text(Group, TEXT("selected"));
        for (const auto& VariantValue : Array(Group, TEXT("variants")))
        {
            auto Variant = VariantValue->AsObject();
            if (Text(Variant, TEXT("id")) == Selected)
                for (const auto& Part : Array(Variant, TEXT("occludes"))) Covered.Add(Part->AsString());
        }
    }
    for (auto& Part : Parts)
    {
        auto* Component = Part.Component.Get();
        if (!Component) continue;
        Component->SetVisibility(Visible.FindRef(Part.Name) && !Covered.Contains(Part.Name), true);
        if (auto* Material = Part.Material.Get())
        {
            auto Color = Part.Color;
            Color.A *= Part.Opacity[FMath::Min(Frame, Part.Opacity.Num() - 1)];
            Material->SetVectorParameterValue(ColorParameter, Color);
            if (!Part.Textures.IsEmpty() && Definition)
                if (const auto* Texture = Definition->Textures.Find(Part.Textures[FMath::Min(Frame, Part.Textures.Num() - 1)]))
                    Material->SetTextureParameterValue(TextureParameter, Texture->Get());
        }
        if (DriveSingleNodeAnimations)
            if (auto* Skeletal = Cast<USkeletalMeshComponent>(Component))
                if (Skeletal->GetAnimationMode() == EAnimationMode::AnimationSingleNode)
                    Skeletal->SetPosition(Time, false);
    }
}
