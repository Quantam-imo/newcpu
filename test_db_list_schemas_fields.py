import databento as db

client = db.Historical("REDACTED")

dataset = "GLBX.MDP3"

# List all available schemas for the dataset
dataset_schemas = client.metadata.list_schemas(dataset=dataset)
print(f"Schemas for {dataset}:", dataset_schemas)

# Try to list fields for each schema (to infer symbol field)
for schema in dataset_schemas:
    try:
        fields = client.metadata.list_fields(dataset=dataset, schema=schema)
        print(f"Fields for schema {schema}: {fields}")
    except Exception as e:
        print(f"Error listing fields for schema {schema}: {e}")
