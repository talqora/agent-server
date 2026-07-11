-- AlterTable
ALTER TABLE "runs" ADD COLUMN     "task_session_id" INTEGER;

-- CreateTable
CREATE TABLE "task_sessions" (
    "id" SERIAL NOT NULL,
    "user_id" INTEGER NOT NULL,
    "title" VARCHAR(255) NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "task_sessions_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "task_sessions_user_id_updated_at_idx" ON "task_sessions"("user_id", "updated_at");

-- CreateIndex
CREATE INDEX "runs_task_session_id_idx" ON "runs"("task_session_id");

-- AddForeignKey
ALTER TABLE "task_sessions" ADD CONSTRAINT "task_sessions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "runs" ADD CONSTRAINT "runs_task_session_id_fkey" FOREIGN KEY ("task_session_id") REFERENCES "task_sessions"("id") ON DELETE CASCADE ON UPDATE CASCADE;
