# 模擬 CV — 給 JOB RADAR 試用

呢個 folder 入面有 3 份不同行業嘅模擬 CV（純文字 `.txt`，可以直接喺
JOB RADAR 嘅「📄 上傳 CV」 tab 上載）：

| 檔案 | 行業 | 經驗 | 適合測試 |
|---|---|---|---|
| `cv_senior_accountant.txt` | 會計／審計 | 7 年 | cpjobs / CTgoodjobs 嘅 Accountant、Finance Manager 等 |
| `cv_marketing_manager.txt` | 數碼營銷／品牌 | 5 年 | Marketing Manager、Digital Marketing、Brand 等 |
| `cv_software_engineer.txt` | 後端／DevOps | 6 年 | Software Engineer、Backend、SRE、Cloud 等 |

## 點用

1. 喺 JOB RADAR Tab 1「📄 上傳 CV」點「Browse files」
2. 揀其中一份 `.txt`
3. 系統自動抽取關鍵字（HK 金融／會計 vocab list 為主，所以
   會計 CV 抽到嘅 keyword 最多）
4. 跑一次 scrape（例如 cpjobs + keyword "Accountant"）
5. AI 配對分析會根據呢份 CV 同 JD 比較，輸出 fit score

## 注意

- 全部資料**虛構**，姓名、email、公司、薪酬、日期都係隨機，唔代表任何
  真實人或機構
- `.txt` 格式可以直接讀；如想試 PDF flow，可以喺 Word / Google Docs
  打開 `.txt` 再 Save as PDF 上載
- 想試自己 CV，可以對住呢 3 份格式調整自己嘅內容
