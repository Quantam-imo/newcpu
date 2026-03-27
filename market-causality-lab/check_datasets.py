from backend.utils.dataset_manifest import validate_required_datasets


def main() -> None:
    present, missing = validate_required_datasets("data")

    print("DATA READINESS CHECK")
    print("Present:", len(present))
    for name in present:
        print("  -", name)

    print("Missing:", len(missing))
    for name in missing:
        print("  -", name)

    if missing:
        print("\nSTATUS: INCOMPLETE")
    else:
        print("\nSTATUS: READY")


if __name__ == "__main__":
    main()