/**
 * 应用根模块(Root Module)
 *
 * 接入基础设施模块(全部 @Global())+ 健康检查 controller。
 * 各功能模块(auth/documents/chat/agent)就绪后在 imports 追加。
 */
import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { PrismaModule } from './shared/prisma/prisma.module';
import { RedisModule } from './shared/redis/redis.module';
import { MilvusModule } from './shared/milvus/milvus.module';
import { LlmModule } from './shared/llm/llm.module';
import { RunEngineModule } from './shared/run-engine/run-engine.module';
import { QueueModule } from './shared/queue/queue.module';
import { HealthModule } from './modules/health/health.module';
import { AuthModule } from './modules/auth/auth.module';
import { RunsModule } from './modules/runs/runs.module';
import { DocumentsModule } from './modules/documents/documents.module';
import { ConversationsModule } from './modules/conversations/conversations.module';
import { TaskSessionsModule } from './modules/task-sessions/task-sessions.module';
import { AgentModule } from './modules/agent/agent.module';

@Module({
  imports: [
    // 必须最先加载:把 .env 注入 process.env,供下游(Prisma/Redis/Milvus/LLM)读取。
    // isGlobal 让全应用无需重复 import;容器内无 .env 文件时静默跳过,走 environment 注入。
    ConfigModule.forRoot({ isGlobal: true }),
    PrismaModule,
    RedisModule,
    MilvusModule,
    LlmModule,
    RunEngineModule,
    QueueModule,
    AuthModule,
    HealthModule,
    RunsModule,
    DocumentsModule,
    ConversationsModule,
    TaskSessionsModule,
    AgentModule,
  ],
})
export class AppModule {}
