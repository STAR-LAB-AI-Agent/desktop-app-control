# 脚本与命令行接口测试

该目录集中存放不依赖主智能体循环的脚本和命令行接口测试。

- `api_test.py`：手动调用视觉 API，返回鼠标点击原子操作流，不实际点击。
- `mouse_test.py`：手动验证视觉坐标定位；默认只移动鼠标，传入 `--click` 才点击。
- `test_skill_scripts.py`：通过 `unittest` 自动验证技能脚本、JSON 协议和脚本适配器。
- `test_video_playback_script.py`：自动验证网页视频播放状态检查器。

从项目根目录运行全部自动测试：

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

查看某个技能脚本的命令行协议：

```powershell
python skills/web-video-playback/scripts/inspect_video_playback_state.py --describe
```

手动测试会截图或访问视觉 API，自动测试使用模拟输入，不会操作桌面，也不会访问网络。
