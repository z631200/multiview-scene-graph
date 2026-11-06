# simulation_platform.py
import json
import time
import os
from scene_capture.demo.robot_interface import RobotInterface
from scene_capture.demo.benchmark_referee import Referee
from scene_capture.demo.task_definition import TaskDefinition

class Logger:
    def __init__(self, filepath="trace_log.json"):
        self.filepath = filepath
        self.history = []

    def log_step(self, step, action, target, result, referee_msg, goal_status):
        self.history.append({
            "step": step,
            "timestamp": time.time(),
            "action": action,
            "target": target,
            "success": result["success"],
            "error_message": result["message"],
            "referee_feedback": referee_msg,
            "goal_status": goal_status
        })

    def save(self):
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, indent=4, ensure_ascii=False)
        print(f"[Logger] 紀錄已儲存至 {self.filepath}")

class SimulationPlatform:
    def __init__(
        self, controller, record_video: bool = False,
        video_path: str = "run.mp4", fps: int = 5,
        log_path: str = "trace_log.json",
    ):
        self.controller = controller
        self.robot = RobotInterface(controller, frame_hook=self._on_frame_captured)
        self.referee = Referee()
        self.logger = Logger(log_path)
        self.current_task = None
        self.step_count = 0
        self.record_video = record_video
        self.video_path = video_path
        self.fps = fps
        self._video_writer = None

    def _on_frame_captured(self, frame):
        """
        當 Robot 產生中間幀，或 Step 結束時呼叫此函式將畫面寫入影片。
        """
        if not self.record_video:
            return
        import cv2
        
        if self._video_writer is None:
            if frame is None:
                return
            h, w = frame.shape[:2]
            os.makedirs(os.path.dirname(self.video_path) or ".", exist_ok=True)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._video_writer = cv2.VideoWriter(self.video_path, fourcc, self.fps, (w, h))
            if not self._video_writer.isOpened():
                self._video_writer.release()
                self._video_writer = None
                raise RuntimeError(f"VideoWriter 無法開啟 {self.video_path}")
            print(f"[Video] 開始錄影：{self.video_path} ({w}x{h}, fps={self.fps})")

        if frame is not None:
            self._video_writer.write(frame[:, :, ::-1])

    def load_task(self, task: TaskDefinition):
        self.current_task = task
        print(f"[Platform] 載入任務: {task.instruction}")
        self.controller.reset(**task.get_initial_config())
        self.step_count = 0
        self.logger.history.clear()

        if self.record_video:
            self._on_frame_captured(self.controller.last_event.frame)

    def run_step(self, action: str, target_id=None):
        """AI 呼叫此函式來執行一步"""
        if self.current_task is None:
            raise RuntimeError("Call load_task() before run_step().")
        self.step_count += 1
        result = self.robot.parse_and_execute(action, target_id)
        metadata = self.controller.last_event.metadata

        if self.record_video:
            self._on_frame_captured(self.controller.last_event.frame)

        step_feedback = self.referee.evaluate_step(result)
        task_status = self.referee.check_success(self.current_task, metadata)
        self.logger.log_step(self.step_count, action, target_id, result, step_feedback, task_status)

        return {
            "image": self.controller.last_event.frame,
            "feedback": step_feedback,
            "task_done": task_status["is_success"],
            "goal_details": task_status["details"]
        }

    def finish(self):
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            print(f"[Video] 錄影完成：{self.video_path}")

        self.logger.save()
