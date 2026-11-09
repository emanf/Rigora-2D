#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Engine/DataAsset.h"
#include "RigoraWardrobeComponent.generated.h"

class UMeshComponent;
class UMaterialInstanceDynamic;
class FJsonObject;
class UTexture2D;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_FiveParams(FRigoraAnimationEvent, const FString&, Id, const FString&, Name, const FString&, Type, const FString&, PayloadJson, const FString&, Target);

/** Imported definition asset; geometry stays in native SkeletalMesh assets. */
UCLASS(BlueprintType)
class RIGORARUNTIME_API URigoraDefinition : public UDataAsset
{
    GENERATED_BODY()
public:
    UPROPERTY(EditAnywhere, Category="Rigora", meta=(MultiLine=true, AdvancedDisplay))
    FString DefinitionJson;
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Rigora")
    TMap<FString, TObjectPtr<UTexture2D>> Textures;
};

/** Applies wardrobe choices and independent colors to native imported mesh components. */
UCLASS(ClassGroup=(Rigora), meta=(BlueprintSpawnableComponent))
class RIGORARUNTIME_API URigoraWardrobeComponent : public UActorComponent
{
    GENERATED_BODY()
public:
    URigoraWardrobeComponent();
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Rigora")
    TObjectPtr<URigoraDefinition> Definition;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Rigora")
    bool Playing = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Rigora")
    bool DriveSingleNodeAnimations = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Rigora")
    FName ColorParameter = TEXT("BaseColorFactor");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Rigora")
    FName TextureParameter = TEXT("baseColorTexture");
    UPROPERTY(BlueprintAssignable, Category="Rigora")
    FRigoraAnimationEvent OnAnimationEvent;
    UFUNCTION(BlueprintCallable, Category="Rigora")
    bool InitializeRig();
    UFUNCTION(BlueprintCallable, Category="Rigora")
    bool BindPart(const FString& PartName, UMeshComponent* Component);
    UFUNCTION(BlueprintCallable, Category="Rigora")
    bool SetClothing(const FString& GroupId, const FString& VariantId);
    UFUNCTION(BlueprintCallable, Category="Rigora")
    bool SetPartColor(const FString& PartName, FLinearColor Color);
    UFUNCTION(BlueprintCallable, Category="Rigora")
    void Seek(float Seconds);
    UFUNCTION(BlueprintPure, Category="Rigora")
    float GetTime() const { return Time; }
protected:
    virtual void BeginPlay() override;
    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
private:
    struct FPart
    {
        FString Name;
        TArray<bool> Visible;
        TArray<float> Opacity;
        TArray<FString> Textures;
        TWeakObjectPtr<UMeshComponent> Component;
        TWeakObjectPtr<UMaterialInstanceDynamic> Material;
        FLinearColor Color = FLinearColor::White;
    };
    TSharedPtr<FJsonObject> Data;
    TArray<FPart> Parts;
    TMap<FString, FString> Selections;
    float Time = 0;
    float FPS = 24;
    float Duration = 0;
    bool Loop = false;
    bool EventStarted = false;
    void ApplyState();
    void EmitEvents(float Previous, float Candidate);
};
