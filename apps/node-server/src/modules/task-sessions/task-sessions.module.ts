import { Module } from '@nestjs/common';
import { TaskSessionsController } from './task-sessions.controller';
import { TaskSessionsService } from './task-sessions.service';

/**
 * task-sessions 模块:任务会话 CRUD(镜像 conversations)。
 *
 * Prisma 来自 @Global(),无需 imports。exports TaskSessionsService 供 AgentModule
 * 在提交任务时做归属校验 + 触碰会话。
 */
@Module({
  controllers: [TaskSessionsController],
  providers: [TaskSessionsService],
  exports: [TaskSessionsService],
})
export class TaskSessionsModule {}
