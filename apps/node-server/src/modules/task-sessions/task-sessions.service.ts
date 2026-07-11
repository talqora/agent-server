import { Injectable, NotFoundException } from '@nestjs/common';
import type { Run, RunEvent, TaskSession } from '@prisma/client';
import { PrismaService } from '../../shared/prisma/prisma.service';
import { CreateTaskSessionDto } from './dto/create-task-session.dto';

/**
 * 任务会话的持久化层(纯 CRUD,无编排逻辑)。
 *
 * 镜像 ConversationsService:TaskSession 之于 Run,如同 Conversation 之于 Message。
 * 所有读写按 userId 做归属校验——多租户隔离,会话本身必须按 user 限定。
 * agent 任务的提交/编排在 AgentController + worker,不在这里。
 */
@Injectable()
export class TaskSessionsService {
  constructor(private readonly prisma: PrismaService) {}

  create(userId: number, dto: CreateTaskSessionDto): Promise<TaskSession> {
    return this.prisma.taskSession.create({
      data: { userId, title: dto.title ?? '新任务会话' },
    });
  }

  list(userId: number): Promise<TaskSession[]> {
    return this.prisma.taskSession.findMany({
      where: { userId },
      orderBy: { updatedAt: 'desc' },
    });
  }

  /** 取会话 + 全量 run(按创建升序,含各 run 的事件流),含归属校验 */
  async get(
    userId: number,
    id: number,
  ): Promise<TaskSession & { runs: (Run & { events: RunEvent[] })[] }> {
    const session = await this.prisma.taskSession.findUnique({
      where: { id },
      include: {
        runs: {
          include: { events: { orderBy: { sequenceNo: 'asc' } } },
          orderBy: { createdAt: 'asc' },
        },
      },
    });
    if (!session || session.userId !== userId) {
      throw new NotFoundException('任务会话不存在或无权访问');
    }
    return session;
  }

  /** 仅校验归属并返回会话本身(不拉 runs),供 AgentController 提交时用 */
  async ensureOwned(userId: number, id: number): Promise<TaskSession> {
    const session = await this.prisma.taskSession.findUnique({ where: { id } });
    if (!session || session.userId !== userId) {
      throw new NotFoundException('任务会话不存在或无权访问');
    }
    return session;
  }

  /** 删会话:Run / RunEvent 走 Prisma(DB)级联删,无外部资源要清 */
  async delete(userId: number, id: number): Promise<{ id: number }> {
    const session = await this.ensureOwned(userId, id);
    await this.prisma.taskSession.delete({ where: { id: session.id } });
    return { id: session.id };
  }

  /**
   * 提交任务时触碰会话:刷新 updatedAt(用于列表按最近活跃排序);
   * 若标题仍是默认值,用首个任务文本回填(截断 255)。归属校验内含。
   */
  async touchOnSubmit(
    userId: number,
    id: number,
    taskText: string,
  ): Promise<TaskSession> {
    const session = await this.ensureOwned(userId, id);
    return this.prisma.taskSession.update({
      where: { id: session.id },
      data: {
        updatedAt: new Date(),
        ...(session.title === '新任务会话'
          ? { title: taskText.slice(0, 255) }
          : {}),
      },
    });
  }
}
