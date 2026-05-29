# 台股盤後焦點機器人 🤖

每個工作日台灣時間 **18:30** 自動透過 Telegram 推播盤後摘要，週五額外附上本週大盤走勢圖。

## 功能

- **每日盤後推播**：加權指數、漲跌幅、成交金額、台積電 (2330) 與元大台灣50 (0050) 收盤資訊
- **週五週報圖表**：最近 5 個交易日的大盤折線圖（台股慣例：紅漲綠跌），透過 Telegram `sendPhoto` 發送

## 資料來源

| 資料 | API |
|---|---|
| 大盤指數 | TWSE `FMTQIK` |
| 個股收盤 | TWSE `STOCK_DAY_ALL` (open_data) |

## 部署

1. Fork 或 Clone 此 repo
2. 在 GitHub Repo → **Settings → Secrets and variables → Actions** 新增：
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. GitHub Actions 排程自動於每個工作日 UTC 06:30（台灣 14:30）執行

## 本機執行

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id
python bot.py
```
