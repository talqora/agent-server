import { describe, it, expect, vi, type Mock } from 'vitest';
import { NotFoundException } from '@nestjs/common';
import type { TaskSession } from '@prisma/client';
import { TaskSessionsService } from './task-sessions.service';
import type { PrismaService } from '../../shared/prisma/prisma.service';

type PrismaMocks = {
  create: Mock;
  findMany: Mock;
  findUnique: Mock;
  update: Mock;
  delete: Mock;
};

function makeService(): { service: TaskSessionsService; p: PrismaMocks } {
  const p: PrismaMocks = {
    create: vi.fn(),
    findMany: vi.fn(),
    findUnique: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  };
  const prisma = { taskSession: p } as unknown as PrismaService;
  return { service: new TaskSessionsService(prisma), p };
}

function session(over: Partial<TaskSession> = {}): TaskSession {
  return {
    id: 1,
    userId: 7,
    title: '新任务会话',
    createdAt: new Date('2026-01-01'),
    updatedAt: new Date('2026-01-01'),
    ...over,
  } as TaskSession;
}

describe('TaskSessionsService', () => {
  it('create:标题缺省落 "新任务会话"', async () => {
    const { service, p } = makeService();
    p.create.mockResolvedValue(session());

    await service.create(7, {});

    expect(p.create).toHaveBeenCalledWith({
      data: { userId: 7, title: '新任务会话' },
    });
  });

  it('create:传标题则用传入值', async () => {
    const { service, p } = makeService();
    p.create.mockResolvedValue(session({ title: '我的任务' }));

    await service.create(7, { title: '我的任务' });

    expect(p.create).toHaveBeenCalledWith({
      data: { userId: 7, title: '我的任务' },
    });
  });

  it('list:按 userId 过滤 + updatedAt 降序', async () => {
    const { service, p } = makeService();
    p.findMany.mockResolvedValue([session()]);

    await service.list(7);

    expect(p.findMany).toHaveBeenCalledWith({
      where: { userId: 7 },
      orderBy: { updatedAt: 'desc' },
    });
  });

  it('get:归属匹配时返回会话(含 runs.events,按序)', async () => {
    const { service, p } = makeService();
    const withRuns = { ...session(), runs: [{ id: 10, events: [] }] };
    p.findUnique.mockResolvedValue(withRuns);

    const got = await service.get(7, 1);

    expect(got).toBe(withRuns);
    expect(p.findUnique).toHaveBeenCalledWith({
      where: { id: 1 },
      include: {
        runs: {
          include: { events: { orderBy: { sequenceNo: 'asc' } } },
          orderBy: { createdAt: 'asc' },
        },
      },
    });
  });

  it('get:userId 不匹配 → NotFoundException', async () => {
    const { service, p } = makeService();
    p.findUnique.mockResolvedValue({ ...session({ userId: 999 }), runs: [] });

    await expect(service.get(7, 1)).rejects.toBeInstanceOf(NotFoundException);
  });

  it('get:会话不存在 → NotFoundException', async () => {
    const { service, p } = makeService();
    p.findUnique.mockResolvedValue(null);

    await expect(service.get(7, 1)).rejects.toBeInstanceOf(NotFoundException);
  });

  it('delete:ensureOwned 通过后调 prisma.taskSession.delete', async () => {
    const { service, p } = makeService();
    p.findUnique.mockResolvedValue(session());
    p.delete.mockResolvedValue(session());

    const res = await service.delete(7, 1);

    expect(p.delete).toHaveBeenCalledWith({ where: { id: 1 } });
    expect(res).toEqual({ id: 1 });
  });

  it('delete:非本人会话 → NotFoundException,不调 delete', async () => {
    const { service, p } = makeService();
    p.findUnique.mockResolvedValue(session({ userId: 999 }));

    await expect(service.delete(7, 1)).rejects.toBeInstanceOf(NotFoundException);
    expect(p.delete).not.toHaveBeenCalled();
  });

  it('touchOnSubmit:标题为默认值时用任务文本回填并刷新 updatedAt', async () => {
    const { service, p } = makeService();
    p.findUnique.mockResolvedValue(session({ title: '新任务会话' }));
    p.update.mockResolvedValue(session({ title: '整理资料' }));

    await service.touchOnSubmit(7, 1, '整理资料');

    expect(p.update).toHaveBeenCalledTimes(1);
    const arg = p.update.mock.calls[0][0];
    expect(arg.where).toEqual({ id: 1 });
    expect(arg.data.title).toBe('整理资料');
    expect(arg.data.updatedAt).toBeInstanceOf(Date);
  });

  it('touchOnSubmit:回填时任务文本截断到 255 字符', async () => {
    const { service, p } = makeService();
    p.findUnique.mockResolvedValue(session({ title: '新任务会话' }));
    p.update.mockResolvedValue(session());
    const long = 'x'.repeat(300);

    await service.touchOnSubmit(7, 1, long);

    expect(p.update.mock.calls[0][0].data.title).toHaveLength(255);
  });

  it('touchOnSubmit:标题非默认值时不覆盖标题(只刷新 updatedAt)', async () => {
    const { service, p } = makeService();
    p.findUnique.mockResolvedValue(session({ title: '已命名' }));
    p.update.mockResolvedValue(session({ title: '已命名' }));

    await service.touchOnSubmit(7, 1, '新任务文本');

    const arg = p.update.mock.calls[0][0];
    expect(arg.data.title).toBeUndefined();
    expect(arg.data.updatedAt).toBeInstanceOf(Date);
  });

  it('touchOnSubmit:非本人会话 → NotFoundException,不调 update', async () => {
    const { service, p } = makeService();
    p.findUnique.mockResolvedValue(session({ userId: 999 }));

    await expect(service.touchOnSubmit(7, 1, 'x')).rejects.toBeInstanceOf(
      NotFoundException,
    );
    expect(p.update).not.toHaveBeenCalled();
  });
});
