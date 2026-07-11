import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  ParseIntPipe,
  Post,
} from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { CurrentUser } from '../auth/current-user.decorator';
import type { AuthedUser } from '../auth/jwt.strategy';
import { TaskSessionsService } from './task-sessions.service';
import { CreateTaskSessionDto } from './dto/create-task-session.dto';

@ApiTags('agent-sessions')
@Controller('agent/sessions')
export class TaskSessionsController {
  constructor(private readonly sessions: TaskSessionsService) {}

  @Post()
  @ApiOperation({ summary: '新建任务会话' })
  create(@CurrentUser() user: AuthedUser, @Body() dto: CreateTaskSessionDto) {
    return this.sessions.create(user.userId, dto);
  }

  @Get()
  @ApiOperation({ summary: '列出当前用户的任务会话' })
  list(@CurrentUser() user: AuthedUser) {
    return this.sessions.list(user.userId);
  }

  @Get(':id')
  @ApiOperation({ summary: '取任务会话(含全量 run 与事件流)' })
  get(@CurrentUser() user: AuthedUser, @Param('id', ParseIntPipe) id: number) {
    return this.sessions.get(user.userId, id);
  }

  @Delete(':id')
  @HttpCode(204)
  @ApiOperation({ summary: '删任务会话(run / 事件走 Prisma 级联删)' })
  async delete(
    @CurrentUser() user: AuthedUser,
    @Param('id', ParseIntPipe) id: number,
  ): Promise<void> {
    await this.sessions.delete(user.userId, id);
  }
}
