from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    foundry_project_endpoint: str = ""
    foundry_model_deployment_name: str = "gpt-4o"
    fabric_data_agent_server_url: str = ""
    fabric_data_agent_tool_name: str = ""
    fabric_tool_mode: str = "fabric_data_agent"  # or "fabric_query"


settings = Settings()
