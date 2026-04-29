"""
股票数据同步模块
每日凌晨3点从adata同步A股数据
"""
import adata
import pandas as pd
import logging
from datetime import datetime
from pypinyin import lazy_pinyin
import time

logger = logging.getLogger(__name__)

def fetch_stocks_from_adata():
    """
    从 adata 获取所有 A 股股票数据
    返回 DataFrame，包含 code, name, pinyin, pinyin_abbr, market 列
    """
    logger.info("=" * 70)
    logger.info("开始从 adata 获取 A 股股票列表")
    logger.info("=" * 70)

    try:
        logger.info("正在获取股票数据...")
        df = adata.stock.info.all_code()

        logger.info(f"✓ 获取到 {len(df)} 条数据")

        # 重命名列
        df = df.rename(columns={
            'stock_code': 'code',
            'short_name': 'name',
            'exchange': 'market'
        })

        # 数据验证
        if len(df) == 0:
            raise Exception('未获取到任何股票数据')

        # 去重排序
        before = len(df)
        df = df.drop_duplicates(subset=["code"])
        df = df.sort_values("code").reset_index(drop=True)
        after = len(df)

        logger.info(f"去重: {before} -> {after}")

        if after == 0:
            raise Exception('去重后没有有效股票数据')

        # 提取并处理数据
        processed_data = []
        for _, row in df.iterrows():
            code = str(row['code']).strip()
            name = str(row['name']).strip()
            market = str(row['market']).strip().upper()

            # 生成拼音
            py = lazy_pinyin(name)
            pinyin_full = ''.join(py)
            pinyin_abbr = ''.join([x[0] for x in py])

            # 市场代码转换
            if market == 'SH':
                market_code = 'sh'
            elif market == 'SZ':
                market_code = 'sz'
            elif market == 'BJ':
                market_code = 'bj'
            else:
                market_code = 'other'

            processed_data.append({
                'code': code,
                'name': name,
                'pinyin': pinyin_full,
                'pinyin_abbr': pinyin_abbr,
                'market': market_code,
                'status': 1
            })

        df_final = pd.DataFrame(processed_data)

        logger.info(f"✓ 处理完成，共 {len(df_final)} 只股票")
        logger.info(f"  上海: {len(df_final[df_final['market']=='sh'])}")
        logger.info(f"  深圳: {len(df_final[df_final['market']=='sz'])}")
        logger.info(f"  北京: {len(df_final[df_final['market']=='bj'])}")

        return df_final

    except Exception as e:
        raise Exception(f'从 adata 获取股票数据失败: {str(e)}')


def save_to_database(df_stocks):
    """
    保存股票数据到数据库（增量更新）
    """
    from database import get_db_connection

    conn = get_db_connection()
    cursor = conn.cursor()

    start_time = time.time()
    new_count = 0
    update_count = 0
    error_count = 0

    try:
        # 获取现有股票代码
        cursor.execute("SELECT code FROM stocks WHERE status = 1")
        existing_codes = set(row[0] for row in cursor.fetchall())

        logger.info(f"现有股票: {len(existing_codes)} 只")

        # 批量插入/更新
        for _, row in df_stocks.iterrows():
            try:
                if row['code'] in existing_codes:
                    # 更新
                    cursor.execute("""
                        UPDATE stocks
                        SET name = ?, pinyin = ?, pinyin_abbr = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE code = ?
                    """, (row['name'], row['pinyin'], row['pinyin_abbr'], row['code']))
                    update_count += 1
                else:
                    # 新增
                    cursor.execute("""
                        INSERT INTO stocks (code, name, pinyin, pinyin_abbr, market, status)
                        VALUES (?, ?, ?, ?, ?, 1)
                    """, (row['code'], row['name'], row['pinyin'], row['pinyin_abbr'], row['market']))
                    new_count += 1
            except Exception as e:
                logger.error(f"保存股票 {row['code']} 失败: {e}")
                error_count += 1

        # 提交事务
        conn.commit()

        # 记录同步日志
        duration = int(time.time() - start_time)
        cursor.execute("""
            INSERT INTO stock_sync_logs (sync_time, total_count, new_count, update_count, error_count, status, duration_seconds)
            VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, 'success', ?)
        """, (len(df_stocks), new_count, update_count, error_count, duration))

        conn.commit()

        logger.info("=" * 70)
        logger.info(f"同步完成！")
        logger.info(f"  总数: {len(df_stocks)}")
        logger.info(f"  新增: {new_count}")
        logger.info(f"  更新: {update_count}")
        logger.info(f"  错误: {error_count}")
        logger.info(f"  耗时: {duration}秒")
        logger.info("=" * 70)

        return {
            'total': len(df_stocks),
            'new': new_count,
            'update': update_count,
            'error': error_count,
            'duration': duration
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"保存到数据库失败: {e}")

        # 记录失败日志
        try:
            cursor.execute("""
                INSERT INTO stock_sync_logs (sync_time, total_count, new_count, update_count, error_count, status, error_message, duration_seconds)
                VALUES (CURRENT_TIMESTAMP, 0, 0, 0, 0, 'failed', ?, 0)
            """, (str(e),))
            conn.commit()
        except:
            pass

        raise
    finally:
        conn.close()


def sync_stock_data():
    """定时任务入口函数：同步股票数据"""
    logger.info("定时任务触发：开始同步股票数据...")

    try:
        # 1. 从adata获取数据
        df_stocks = fetch_stocks_from_adata()

        # 2. 保存到数据库
        result = save_to_database(df_stocks)

        logger.info("✓ 定时任务执行成功")
        return result

    except Exception as e:
        logger.error(f"✗ 定时任务执行失败: {e}")
        return None


if __name__ == '__main__':
    # 测试用：直接运行同步
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    sync_stock_data()
