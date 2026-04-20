from azure.identity import DefaultAzureCredential

# Singleton credential — caches tokens internally.
# Uses Managed Identity automatically when running inside Azure;
# falls back to env vars → VS Code → Azure CLI → etc. when running locally.
credential = DefaultAzureCredential()
