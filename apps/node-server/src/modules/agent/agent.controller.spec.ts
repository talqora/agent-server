import { describe, it, expect, vi, type Mock } from 'vitest';
import { NotFoundException } from '@nestjs/common';
import type { Queue } from 'bullmq';
import type { Run, TaskSession } from '@prisma/client';
import { AgentController } from './agent.controller';
import type { RunEngineService } from '../../shared/run-engine/run-engine.service';
import type { RunJobData } from '../../shared/queue/queue.types';
import type { TaskSessionsService } from '../task-sessions/task-sessions.service';
import type { AuthedUser } from '../auth/jwt.strategy';

type Mocks = {
  add: Mock;
  createRun: Mock;
  ensureOwned: Mock;
  touchOnSubmit: Mock;
  controller: AgentController;
};

function makeController(): Mocks {
  const add = vi.fn().mockResolvedValue(undefined);
  const createRun = vi.fn();
  const ensureOwned = vi.fn();
  const touchOnSubmit = vi.fn().mockResolvedValue(undefined);
  const queue = { add } as unknown as Queue<RunJobData>;
  const runEngine = { createRun } as unknown as RunEngineService;
  const taskSessions = {
    ensureOwned,
    touchOnSubmit,
  } as unknown as TaskSessionsService;
  return {
    add,
    createRun,
    ensureOwned,
    touchOnSubmit,
    controller: new AgentController(queue, runEngine, taskSessions),
  };
}

const user: AuthedUser = { userId: 7, username: 'u', role: 'USER', scope: [] };

describe('AgentController.createTask', () => {
  it('会话归属通过:createRun 带 taskSessionId,入队,回填标题,返回 runId', async () => {
    const m = makeController();
    m.ensureOwned.mockResolvedValue({ id: 5, userId: 7 } as TaskSession);
    m.createRun.mockResolvedValue({ runId: 'run-abc' } as Run);

    const res = await m.controller.createTask(user, {
      task: '整理我的文档',
      sessionId: 5,
    });

    expect(m.ensureOwned).toHaveBeenCalledWith(7, 5);
    expect(m.createRun).toHaveBeenCalledWith({
      userId: 7,
      kind: 'agent_task',
      task: '整理我的文档',
      taskSessionId: 5,
    });
    expect(m.add).toHaveBeenCalledWith('agent', {
      runId: 'run-abc',
      userId: 7,
    });
    expect(m.touchOnSubmit).toHaveBeenCalledWith(7, 5, '整理我的文档');
    expect(res).toEqual({ runId: 'run-abc' });
  });

  it('会话非本人:ensureOwned 抛 404,不建 run、不入队、不回填', async () => {
    const m = makeController();
    m.ensureOwned.mockRejectedValue(
      new NotFoundException('任务会话不存在或无权访问'),
    );

    await expect(
      m.controller.createTask(user, { task: '整理', sessionId: 999 }),
    ).rejects.toBeInstanceOf(NotFoundException);

    expect(m.createRun).not.toHaveBeenCalled();
    expect(m.add).not.toHaveBeenCalled();
    expect(m.touchOnSubmit).not.toHaveBeenCalled();
  });
});
