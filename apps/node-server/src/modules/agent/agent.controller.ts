import { Body, Controller, HttpCode, Post } from '@nestjs/common';
import { InjectQueue } from '@nestjs/bullmq';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { Queue } from 'bullmq';
import { RunEngineService } from '../../shared/run-engine/run-engine.service';
import { RUNS_QUEUE, type RunJobData } from '../../shared/queue/queue.types';
import { CurrentUser } from '../auth/current-user.decorator';
import type { AuthedUser } from '../auth/jwt.strategy';
import { TaskSessionsService } from '../task-sessions/task-sessions.service';
import { CreateTaskDto } from './dto/create-task.dto';

/**
 * agent 任务入口(web 进程):只负责建 run + 入队,真正的工具编排在 worker 跑。
 * 进度经 SSE `GET /runs/:runId/stream` 订阅(与摄取/demo 共用同一套 run 事件流)。
 */
@ApiTags('agent')
@Controller('agent')
export class AgentController {
  constructor(
    @InjectQueue(RUNS_QUEUE) private readonly runsQueue: Queue<RunJobData>,
    private readonly runEngine: RunEngineService,
    private readonly taskSessions: TaskSessionsService,
  ) {}

  @Post('tasks')
  @HttpCode(202)
  @ApiOperation({
    summary: '提交 agent 任务,返回 runId(经 /runs/:runId/stream 订阅进度)',
  })
  async createTask(
    @CurrentUser() user: AuthedUser,
    @Body() dto: CreateTaskDto,
  ): Promise<{ runId: string }> {
    // 先校验会话归属:非本人会话直接 404,不建 run、不入队
    const session = await this.taskSessions.ensureOwned(
      user.userId,
      dto.sessionId,
    );
    const run = await this.runEngine.createRun({
      userId: user.userId,
      kind: 'agent_task',
      task: dto.task.slice(0, 255),
      taskSessionId: session.id,
    });
    await this.runsQueue.add('agent', {
      runId: run.runId,
      userId: user.userId,
    });
    // 触碰会话:刷新排序时间 + 首个任务回填标题
    await this.taskSessions.touchOnSubmit(user.userId, session.id, dto.task);
    return { runId: run.runId };
  }
}
