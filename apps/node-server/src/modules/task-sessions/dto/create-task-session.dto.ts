import { IsOptional, IsString, MaxLength, MinLength } from 'class-validator';

export class CreateTaskSessionDto {
  // 标题可选;缺省时由首个提交的任务文本或默认值生成
  @IsOptional()
  @IsString()
  @MinLength(1)
  @MaxLength(255)
  title?: string;
}
