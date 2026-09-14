"""服务配置基类:多服务公共配置项。

设计约束(见 docs/技术方案/边界校验策略):
- 配置是**信任边界**之一:用 pydantic-settings 在启动时校验,错/缺 → 启动即炸;
- 业务代码禁止散读 os.environ;一切配置经 Settings 注入;
- 各服务继承本类追加自己的字段(rag-server: milvus / llm / 存储目录等)。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """多服务公共配置。字段名 ↔ 环境变量名大小写不敏感(database_url ← DATABASE_URL)。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 运行环境:development / production / test
    env: str = "development"
    log_level: str = "INFO"

    # ── 基础设施 ──
    database_url: str  # 必填:postgresql+asyncpg://...
    redis_url: str = "redis://localhost:6380"
    pulsar_url: str = "pulsar://localhost:6650"

    # ── 鉴权(双模)──
    # RS256 + JWKS:our-chat 是 IdP,本服务用其公钥验签(不自签发对外 token)
    oauth_issuer: str = ""
    oauth_jwks_uri: str = ""
    # HS256 兜底(本地注册/登录签发的 token;开发路径)
    jwt_secret: str = "dev-secret"
    jwt_expire_seconds: int = 7200

    # ── CORS ──
    # 逗号分隔精确 origin 列表;留空时 dev 反射任意 origin,生产拒绝所有跨源
    cors_origins: str = ""

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
