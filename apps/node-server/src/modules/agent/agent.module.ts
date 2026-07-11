import { Module } from '@nestjs/common';
import { QueueModule } from '../../shared/queue/queue.module';
import { TaskSessionsModule } from '../task-sessions/task-sessions.module';
import { AgentController } from './agent.controller';

/**
 * agent 模块(web 侧):只装 controller(建 run + 入队)。
 *
 * 工具编排(AgentRunnerService / ToolRegistry)只在 worker 进程加载,见 worker.module.ts。
 * RunEngineService 来自 @Global();imports QueueModule 拿 runs 队列生产端句柄,
 * imports TaskSessionsModule 拿 TaskSessionsService(提交时做会话归属校验 + 触碰)。
 */
@Module({
  imports: [QueueModule, TaskSessionsModule],
  controllers: [AgentController],
})
export class AgentModule {}
