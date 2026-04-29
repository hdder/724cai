#!/bin/bash

# 724财讯系统 - 智能部署脚本
# 自动检测改动并上传所有修改的文件
# 同时同步到 /Users/hesiyuan/Code/724CX 备份目录
#
# 说明：
# - 只上传代码文件，不上传 venv, node_modules, logs 等
# - 使用 MD5 对比本地和服务器文件，只上传有改动的
# - 自动同步服务器数据库文件到本地
# - 自动重启服务：./stop.sh && sleep 2 && ./start.sh
# - 自动备份到 724CX 目录
#
# 使用方法：
#   ./deploy_to_server.sh

echo "================================"
echo "  724财讯系统 - 智能部署 + 备份"
echo "================================"
echo ""
echo "📋 监控的代码文件："
echo "   - backend/*.py (Python 代码)"
echo "   - websocket/*.js (Node.js 代码)"
echo "   - frontend/*.html (前端页面)"
echo "   - README/*.md (文档文件夹)"
echo "   - README.md (项目说明)"
echo "   - *.sh (启动脚本)"
echo "   "
echo "   排除：venv/, node_modules/, logs/"
echo ""
echo "📦 自动同步："
echo "   - 服务器数据库文件 → 本地（如有改动）"
echo "   - 变动文件 → /Users/hesiyuan/Code/724CX (备份)"
echo ""

# 服务器配置
SERVER_HOST="root@111.228.8.17"
SERVER_PASSWORD="1998113Yd2022"
SERVER_PATH="/home/724caixun"
LOCAL_PATH="/Users/hesiyuan/Code/724caixun"
BACKUP_PATH="/Users/hesiyuan/Code/724CX"

# 数据库文件配置
REMOTE_DB="${SERVER_PATH}/websocket/data/push_messages.db"
LOCAL_DB="${LOCAL_PATH}/websocket/data/push_messages.db"
LOCAL_DB_BACKUP="${LOCAL_PATH}/websocket/data/push_messages.db.backup"

# 使用 sshpass 自动输入密码（必须在这里定义，后面扫描服务器需要用到）
USE_SSHPASS=false
if command -v sshpass &> /dev/null; then
    USE_SSHPASS=true
    echo "✓ 检测到 sshpass，将使用自动登录"
else
    echo "⚠️  未安装 sshpass，需要手动输入密码"
    echo "   安装方法: brew install hudochenkov/sshpass/sshpass"
fi
echo ""

# ============================================
# 函数：备份文件到724CX目录
# ============================================
backup_to_724cx() {
    local file=$1
    local local_file="${LOCAL_PATH}/${file}"
    local backup_file="${BACKUP_PATH}/${file}"

    # 创建备份目录
    local backup_dir=$(dirname "$backup_file")
    mkdir -p "$backup_dir"

    # 复制文件
    cp "$local_file" "$backup_file"
}

# 函数：git提交备份目录
# ============================================
git_commit_backup() {
    echo ""
    echo "📤 Git提交备份目录..."

    # 检查备份目录是否是git仓库
    if [ ! -d "${BACKUP_PATH}/.git" ]; then
        echo "⚠️  备份目录不是git仓库，跳过提交"
        echo "   提示: cd ${BACKUP_PATH} && git init"
        return 0
    fi

    # 生成提交信息（当前时间）
    local commit_msg="备份 $(date '+%Y年%m月%d日%H:%M:%S')"

    # 切换到备份目录执行git命令
    cd "${BACKUP_PATH}"

    # 添加所有变动
    git add -A .

    # 检查是否有改动
    if git diff --staged --quiet; then
        echo "ℹ️  没有新的改动需要提交"
        cd "${LOCAL_PATH}"
        return 0
    fi

    # 提交
    git commit -m "$commit_msg"

    # 推送
    git push -u origin main

    cd "${LOCAL_PATH}"

    if [ $? -eq 0 ]; then
        echo "✓ Git提交成功: $commit_msg"
    else
        echo "⚠️  Git提交失败（可能网络问题或需要配置）"
    fi
}

# ============================================
# 步骤1: 检查并同步服务器数据库文件
# ============================================
echo "🔄 检查服务器数据库文件..."

if [ "$USE_SSHPASS" = true ]; then
    REMOTE_MD5=$(sshpass -p "${SERVER_PASSWORD}" ssh -T ${SERVER_HOST} "md5sum '${REMOTE_DB}' 2>/dev/null | cut -d' ' -f1" 2>/dev/null)
else
    REMOTE_MD5=$(ssh -T ${SERVER_HOST} "md5sum '${REMOTE_DB}' 2>/dev/null | cut -d' ' -f1" 2>/dev/null)
fi

if [ -n "$REMOTE_MD5" ]; then
    # 服务器有数据库文件，检查本地
    if [ -f "$LOCAL_DB" ]; then
        LOCAL_MD5=$(md5 -q "$LOCAL_DB" 2>/dev/null || echo "0")

        if [ "$REMOTE_MD5" != "$LOCAL_MD5" ]; then
            echo "⚠️  检测到服务器数据库有更新"
            echo "   服务器MD5: $REMOTE_MD5"
            echo "   本地MD5:   $LOCAL_MD5"
            echo ""
            echo "💡 提示: 直接回车=跳过，输入y=同步"
            read -p "是否同步服务器数据库到本地？: " confirm_sync

            # 输入y/Y才同步，回车或其他都跳过
            if [[ "$confirm_sync" =~ ^[Yy]$ ]]; then
                echo ""
                echo "📥 开始同步服务器数据库到本地..."

                # 备份本地数据库
                if [ -f "$LOCAL_DB" ]; then
                    cp "$LOCAL_DB" "$LOCAL_DB_BACKUP"
                    echo "✓ 本地数据库已备份到: push_messages.db.backup"
                fi

                # 下载服务器数据库
                echo "   📥 正在下载数据库文件..."
                echo "   源文件: ${REMOTE_DB}"
                echo "   目标文件: ${LOCAL_DB}"

                # 先检查远程文件是否存在
                if [ "$USE_SSHPASS" = true ]; then
                    REMOTE_EXISTS=$(sshpass -p "${SERVER_PASSWORD}" ssh -T ${SERVER_HOST} "[ -f '${REMOTE_DB}' ] && echo 'exists' || echo 'notfound'" 2>/dev/null)
                else
                    REMOTE_EXISTS=$(ssh -T ${SERVER_HOST} "[ -f '${REMOTE_DB}' ] && echo 'exists' || echo 'notfound'" 2>/dev/null)
                fi

                if [ "$REMOTE_EXISTS" != "exists" ]; then
                    echo "   ✗ 远程文件不存在: ${REMOTE_DB}"
                    echo "   ⏭️  跳过同步"
                else
                    # 使用 scp 下载
                    if [ "$USE_SSHPASS" = true ]; then
                        sshpass -p "${SERVER_PASSWORD}" scp "${SERVER_HOST}:${REMOTE_DB}" "${LOCAL_DB}"
                    else
                        scp "${SERVER_HOST}:${REMOTE_DB}" "${LOCAL_DB}"
                    fi

                    if [ $? -eq 0 ]; then
                        echo "   ✓ 数据库同步成功"
                        NEW_MD5=$(md5 -q "$LOCAL_DB" 2>/dev/null || echo "0")
                        echo "   新MD5: $NEW_MD5"
                    else
                        echo "   ✗ 数据库同步失败"
                        if [ -f "$LOCAL_DB_BACKUP" ]; then
                            cp "$LOCAL_DB_BACKUP" "$LOCAL_DB"
                            echo "   ✓ 已从备份恢复"
                        fi
                    fi
                fi
            else
                echo "跳过数据库同步"
            fi
        else
            echo "✓ 数据库文件一致，无需同步"
        fi
    else
        # 本地没有数据库，直接下载
        echo "📥 本地无数据库文件，开始下载..."
        mkdir -p "$(dirname "$LOCAL_DB")"

        if [ "$USE_SSHPASS" = true ]; then
            sshpass -p "${SERVER_PASSWORD}" scp ${SERVER_HOST}:"${REMOTE_DB}" "${LOCAL_DB}"
        else
            scp ${SERVER_HOST}:"${REMOTE_DB}" "${LOCAL_DB}"
        fi

        if [ $? -eq 0 ]; then
            echo "✓ 数据库下载成功"
        else
            echo "✗ 数据库下载失败"
        fi
    fi
else
    echo "ℹ️  服务器暂无数据库文件，跳过同步"
fi

echo ""

# 自动扫描所有代码文件（排除 venv, node_modules, logs 等）
echo "🔍 扫描本地代码文件..."
FILES_TO_WATCH=()

# 扫描 backend 目录 (Python 代码、配置文件，排除 venv)
while IFS= read -r -d '' file; do
    rel_path="${file#$LOCAL_PATH/}"
    FILES_TO_WATCH+=("$rel_path")
done < <(find "$LOCAL_PATH/backend" -type f \( -name "*.py" -o -name "*.txt" -o -name "*.json" \) \
    -not -path "*/venv/*" \
    -not -path "*/__pycache__/*" \
    -not -path "*/logs/*" \
    -not -path "*/.*" \
    -print0 2>/dev/null)

# 扫描 websocket 目录 (Node.js 代码，排除 node_modules)
while IFS= read -r -d '' file; do
    rel_path="${file#$LOCAL_PATH/}"
    FILES_TO_WATCH+=("$rel_path")
done < <(find "$LOCAL_PATH/websocket" -type f \( -name "*.js" -o -name "package.json" \) \
    -not -path "*/node_modules/*" \
    -not -path "*/data/*.db" \
    -not -path "*/logs/*" \
    -not -path "*/.*" \
    -print0 2>/dev/null)

# 扫描 frontend 目录 (前端文件)
while IFS= read -r -d '' file; do
    rel_path="${file#$LOCAL_PATH/}"
    FILES_TO_WATCH+=("$rel_path")
done < <(find "$LOCAL_PATH/frontend" -type f \( -name "*.html" -o -name "*.css" -o -name "*.js" -o -name "*.svg" \) \
    -not -path "*/logs/*" \
    -not -path "*/.*" \
    -print0 2>/dev/null)

# 扫描根目录的启动脚本、配置文件和所有 .md 文件
while IFS= read -r -d '' file; do
    rel_path="${file#$LOCAL_PATH/}"
    FILES_TO_WATCH+=("$rel_path")
done < <(find "$LOCAL_PATH" -maxdepth 1 -type f \( -name "*.sh" -o -name "*.md" -o -name "*.json" \) -print0 2>/dev/null)

# 扫描 README 目录 (文档文件夹)
while IFS= read -r -d '' file; do
    rel_path="${file#$LOCAL_PATH/}"
    FILES_TO_WATCH+=("$rel_path")
done < <(find "$LOCAL_PATH/README" -type f -name "*.md" -print0 2>/dev/null)

echo "✓ 找到 ${#FILES_TO_WATCH[@]} 个代码文件"
echo ""

# 获取服务器上的文件列表
echo "🔍 扫描服务器文件..."
REMOTE_FILES=()

if [ "$USE_SSHPASS" = true ]; then
    SERVER_FILE_LIST=$(sshpass -p "${SERVER_PASSWORD}" ssh ${SERVER_HOST} "find '${SERVER_PATH}/backend' -type f \( -name '*.py' -o -name '*.txt' -o -name '*.json' \) -not -path '*/venv/*' -not -path '*/__pycache__/*' -not -path '*/logs/*' -not -path '*/.*' 2>/dev/null; find '${SERVER_PATH}/websocket' -type f \( -name '*.js' -o -name 'package.json' \) -not -path '*/node_modules/*' -not -path '*/logs/*' -not -path '*/data/*.db' -not -path '*/.*' 2>/dev/null; find '${SERVER_PATH}/frontend' -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.svg' \) -not -path '*/logs/*' -not -path '*/.*' 2>/dev/null; find '${SERVER_PATH}' -maxdepth 1 -type f \( -name '*.sh' -o -name '*.md' -o -name '*.json' \) 2>/dev/null; find '${SERVER_PATH}/README' -type f -name '*.md' 2>/dev/null" 2>/dev/null)
else
    SERVER_FILE_LIST=$(ssh ${SERVER_HOST} "find '${SERVER_PATH}/backend' -type f \( -name '*.py' -o -name '*.txt' -o -name '*.json' \) -not -path '*/venv/*' -not -path '*/__pycache__/*' -not -path '*/logs/*' -not -path '*/.*' 2>/dev/null; find '${SERVER_PATH}/websocket' -type f \( -name '*.js' -o -name 'package.json' \) -not -path '*/node_modules/*' -not -path '*/logs/*' -not -path '*/data/*.db' -not -path '*/.*' 2>/dev/null; find '${SERVER_PATH}/frontend' -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.svg' \) -not -path '*/logs/*' -not -path '*/.*' 2>/dev/null; find '${SERVER_PATH}' -maxdepth 1 -type f \( -name '*.sh' -o -name '*.md' -o -name '*.json' \) 2>/dev/null; find '${SERVER_PATH}/README' -type f -name '*.md' 2>/dev/null" 2>/dev/null)
fi

while IFS= read -r remote_file; do
    if [ -n "$remote_file" ]; then
        rel_path="${remote_file#$SERVER_PATH/}"
        REMOTE_FILES+=("$rel_path")
    fi
done <<< "$SERVER_FILE_LIST"

echo "✓ 服务器上有 ${#REMOTE_FILES[@]} 个代码文件"
echo ""

# 检测服务器上多余的文件
EXTRA_FILES=()
EXTRA_DIRS=()

# 首先收集本地所有的目录路径（使用普通数组，不使用关联数组）
LOCAL_DIRS=""
for local_file in "${FILES_TO_WATCH[@]}"; do
    # 提取文件所在的所有父目录
    dir_path=$(dirname "$local_file")
    while [ "$dir_path" != "." ] && [ "$dir_path" != "" ]; do
        # 检查目录是否已在列表中
        if ! echo "$LOCAL_DIRS" | grep -q "^$dir_path$"; then
            LOCAL_DIRS="$LOCAL_DIRS$dir_path"$'\n'
        fi
        dir_path=$(dirname "$dir_path")
    done
done

# 检测多余的文件和目录
for remote_file in "${REMOTE_FILES[@]}"; do
    exists=false
    for local_file in "${FILES_TO_WATCH[@]}"; do
        if [ "$remote_file" == "$local_file" ]; then
            exists=true
            break
        fi
    done

    if [ "$exists" = false ]; then
        # 检查这个文件所在的目录是否已被删除
        remote_dir=$(dirname "$remote_file")
        dir_deleted=false

        # 检查该目录及其父目录是否在本地存在
        check_dir="$remote_dir"
        while [ "$check_dir" != "." ] && [ "$check_dir" != "" ]; do
            if ! echo "$LOCAL_DIRS" | grep -q "^$check_dir$"; then
                # 这个目录在本地不存在，标记为目录删除
                if ! echo "$EXTRA_DIRS_LIST" | grep -q "^$check_dir$"; then
                    EXTRA_DIRS_LIST="$EXTRA_DIRS_LIST$check_dir"$'\n'
                    EXTRA_DIRS+=("$check_dir")
                fi
                dir_deleted=true
                break
            fi
            check_dir=$(dirname "$check_dir")
        done

        # 只有当文件所在目录未被删除时，才将文件标记为多余文件
        if [ "$dir_deleted" = false ]; then
            EXTRA_FILES+=("$remote_file")
        fi
    fi
done

# 如果有多余目录或文件，提示用户
TOTAL_EXTRA_DIRS=${#EXTRA_DIRS[@]}
if [ ${#EXTRA_FILES[@]} -gt 0 ] || [ $TOTAL_EXTRA_DIRS -gt 0 ]; then
    echo "🗑️  检测到服务器上有 ${#EXTRA_FILES[@]} 个多余文件和 $TOTAL_EXTRA_DIRS 个多余目录："
    echo ""

    # 显示多余目录
    if [ $TOTAL_EXTRA_DIRS -gt 0 ]; then
        echo "📁 多余目录："
        for dir in "${EXTRA_DIRS[@]}"; do
            echo "   - $dir/"
        done
        echo ""
    fi

    # 显示多余文件
    if [ ${#EXTRA_FILES[@]} -gt 0 ]; then
        echo "📄 多余文件："
        for file in "${EXTRA_FILES[@]}"; do
            echo "   - $file"
        done
        echo ""
    fi

    echo "⚠️  这些文件/目录在本地不存在，可能是已删除的内容"
    echo ""
    echo "💡 提示: 直接回车=删除，输入n=保留"
    read -p "是否删除这些文件和目录？: " confirm_delete

    # 回车或输入y/Y都代表确认
    if [[ -z "$confirm_delete" ]] || [[ "$confirm_delete" =~ ^[Yy]$ ]]; then
        echo ""
        echo "🗑️  正在删除服务器上的多余文件和目录..."

        DELETE_SUCCESS=true

        # 删除多余的目录（使用 rm -rf）
        for dir in "${EXTRA_DIRS[@]}"; do
            echo -n "   删除目录 $dir/..."

            if [ "$USE_SSHPASS" = true ]; then
                sshpass -p "${SERVER_PASSWORD}" ssh -T ${SERVER_HOST} "rm -rf '${SERVER_PATH}/${dir}'" >/dev/null 2>&1
            else
                ssh -T ${SERVER_HOST} "rm -rf '${SERVER_PATH}/${dir}'" >/dev/null 2>&1
            fi

            if [ $? -eq 0 ]; then
                echo " ✓"
            else
                echo " ✗ 失败"
                DELETE_SUCCESS=false
            fi
        done

        # 删除多余的文件（使用 rm -f）
        for file in "${EXTRA_FILES[@]}"; do
            echo -n "   删除文件 $file..."

            if [ "$USE_SSHPASS" = true ]; then
                sshpass -p "${SERVER_PASSWORD}" ssh -T ${SERVER_HOST} "rm -f '${SERVER_PATH}/${file}'" >/dev/null 2>&1
            else
                ssh -T ${SERVER_HOST} "rm -f '${SERVER_PATH}/${file}'" >/dev/null 2>&1
            fi

            if [ $? -eq 0 ]; then
                echo " ✓"
            else
                echo " ✗ 失败"
                DELETE_SUCCESS=false
            fi
        done

        echo ""
        if [ "$DELETE_SUCCESS" = true ]; then
            echo "✓ 所有多余文件和目录已删除"
        else
            echo "⚠️  部分文件/目录删除失败"
        fi
    else
        echo "跳过删除"
    fi
    echo ""
else
    echo "✓ 服务器文件列表与本地一致"
    echo ""
fi

# 函数：获取文件MD5
get_md5() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        md5 -q "$1" 2>/dev/null || echo "0"
    else
        md5sum "$1" 2>/dev/null | cut -d' ' -f1 || echo "0"
    fi
}

# 函数：获取远程文件MD5
get_remote_md5() {
    local file=$1
    if [ "$USE_SSHPASS" = true ]; then
        sshpass -p "${SERVER_PASSWORD}" ssh -T ${SERVER_HOST} "if [ -f '${SERVER_PATH}/${file}' ]; then if command -v md5sum &>/dev/null; then md5sum '${SERVER_PATH}/${file}' | cut -d' ' -f1; else md5 -q '${SERVER_PATH}/${file}'; fi; else echo '0'; fi" 2>/dev/null
    else
        ssh -T ${SERVER_HOST} "if [ -f '${SERVER_PATH}/${file}' ]; then if command -v md5sum &>/dev/null; then md5sum '${SERVER_PATH}/${file}' | cut -d' ' -f1; else md5 -q '${SERVER_PATH}/${file}'; fi; else echo '0'; fi" 2>/dev/null
    fi
}

# 函数：上传文件
upload_file() {
    local file=$1
    local local_file="${LOCAL_PATH}/${file}"
    local remote_file="${SERVER_PATH}/${file}"

    echo -n "   上传 ${file}..."

    # 先创建远程目录（如果不存在）
    local remote_dir=$(dirname "$remote_file")
    if [ "$USE_SSHPASS" = true ]; then
        sshpass -p "${SERVER_PASSWORD}" ssh ${SERVER_HOST} "mkdir -p '$remote_dir'" >/dev/null 2>&1
    else
        ssh ${SERVER_HOST} "mkdir -p '$remote_dir'" >/dev/null 2>&1
    fi

    # 再上传文件
    if [ "$USE_SSHPASS" = true ]; then
        sshpass -p "${SERVER_PASSWORD}" scp "${local_file}" ${SERVER_HOST}:"${remote_file}" >/dev/null 2>&1
    else
        scp "${local_file}" ${SERVER_HOST}:"${remote_file}" >/dev/null 2>&1
    fi

    if [ $? -eq 0 ]; then
        echo " ✓"
        # 同时备份到724CX
        backup_to_724cx "$file"
        return 0
    else
        echo " ✗ 失败"
        return 1
    fi
}

echo "🔍 批量获取远程文件MD5..."
echo ""

# 临时文件存储远程MD5
REMOTE_MD5_FILE=$(mktemp)

# 构建远程文件的find命令（一次性获取所有MD5）
FIND_COMMAND="find '${SERVER_PATH}/backend' -type f \( -name '*.py' -o -name '*.txt' -o -name '*.json' \) -not -path '*/venv/*' -not -path '*/__pycache__/*' -not -path '*/logs/*' -not -path '*/.*' -exec md5sum {} \; 2>/dev/null"
FIND_COMMAND="$FIND_COMMAND; find '${SERVER_PATH}/websocket' -type f \( -name '*.js' -o -name 'package.json' \) -not -path '*/node_modules/*' -not -path '*/logs/*' -not -path '*/data/*.db' -not -path '*/.*' -exec md5sum {} \; 2>/dev/null"
FIND_COMMAND="$FIND_COMMAND; find '${SERVER_PATH}/frontend' -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.svg' \) -not -path '*/logs/*' -not -path '*/.*' -exec md5sum {} \; 2>/dev/null"
FIND_COMMAND="$FIND_COMMAND; find '${SERVER_PATH}' -maxdepth 1 -type f \( -name '*.sh' -o -name '*.md' -o -name '*.json' \) -exec md5sum {} \; 2>/dev/null"
FIND_COMMAND="$FIND_COMMAND; find '${SERVER_PATH}/README' -type f -name '*.md' -exec md5sum {} \; 2>/dev/null"

# 批量获取所有远程文件的MD5（一次SSH连接）并保存到临时文件
if [ "$USE_SSHPASS" = true ]; then
    sshpass -p "${SERVER_PASSWORD}" ssh -T ${SERVER_HOST} "$FIND_COMMAND" 2>/dev/null > "$REMOTE_MD5_FILE"
else
    ssh -T ${SERVER_HOST} "$FIND_COMMAND" 2>/dev/null > "$REMOTE_MD5_FILE"
fi

# 显示获取到的远程MD5数量
REMOTE_MD5_COUNT=$(wc -l < "$REMOTE_MD5_FILE" 2>/dev/null || echo "0")
echo "✓ 获取到 $REMOTE_MD5_COUNT 个远程文件MD5"
echo ""

echo "🔍 检查文件改动..."
echo ""

CHANGED_FILES=()
ALL_CHANGED=false

# 函数：从临时文件获取远程MD5
get_remote_md5_from_file() {
    local file=$1
    # md5sum输出格式: "MD5  /完整路径"
    # 精确匹配完整路径
    awk -v path="${SERVER_PATH}/${file}" '$2 == path {print $1}' "$REMOTE_MD5_FILE"
}

# 检查每个文件
for file in "${FILES_TO_WATCH[@]}"; do
    local_file="${LOCAL_PATH}/${file}"

    # 检查本地文件是否存在
    if [ ! -f "$local_file" ]; then
        echo "⚠️  本地文件不存在: $file"
        continue
    fi

    # 获取本地MD5
    local_md5=$(get_md5 "$local_file")

    # 从临时文件获取远程MD5
    remote_md5=$(get_remote_md5_from_file "$file")

    # 比较
    if [ "$local_md5" != "$remote_md5" ]; then
        echo "📝 $file (已修改)"
        CHANGED_FILES+=("$file")
        ALL_CHANGED=true
    fi
done

echo ""

# 清理临时文件
rm -f "$REMOTE_MD5_FILE"

# 定义重启服务函数
restart_services() {
    echo "🔄 正在重启服务..."
    echo ""

    if [ "$USE_SSHPASS" = true ]; then
        sshpass -p "${SERVER_PASSWORD}" ssh -T ${SERVER_HOST} << 'ENDSSH'
cd /home/724caixun

echo "停止服务..."
./stop.sh
echo "等待2秒..."
sleep 2
echo "启动服务..."
./start.sh

echo ""
echo "等待服务启动..."
sleep 5

echo ""
echo "检查服务状态..."
echo ""

# 检查端口
if lsof -i:5555 > /dev/null 2>&1; then
    echo "✓ Flask 服务 (5555) - 运行中"
else
    echo "✗ Flask 服务 (5555) - 未运行"
fi

if lsof -i:9080 > /dev/null 2>&1; then
    echo "✓ Node.js 服务 (9080) - 运行中"
else
    echo "✗ Node.js 服务 (9080) - 未运行"
fi

if lsof -i:8000 > /dev/null 2>&1; then
    echo "✓ 前端服务 (8000) - 运行中"
else
    echo "✗ 前端服务 (8000) - 未运行"
fi

ENDSSH
    else
        ssh ${SERVER_HOST} << 'ENDSSH'
cd /home/724caixun

echo "停止服务..."
./stop.sh
echo "等待2秒..."
sleep 2
echo "启动服务..."
./start.sh

echo ""
echo "等待服务启动..."
sleep 5

echo ""
echo "检查服务状态..."
echo ""

# 检查端口
if lsof -i:5555 > /dev/null 2>&1; then
    echo "✓ Flask 服务 (5555) - 运行中"
else
    echo "✗ Flask 服务 (5555) - 未运行"
fi

if lsof -i:9080 > /dev/null 2>&1; then
    echo "✓ Node.js 服务 (9080) - 运行中"
else
    echo "✗ Node.js 服务 (9080) - 未运行"
fi

if lsof -i:8000 > /dev/null 2>&1; then
    echo "✓ 前端服务 (8000) - 运行中"
else
    echo "✗ 前端服务 (8000) - 未运行"
fi

ENDSSH
    fi
}

# 如果没有改动
if [ "$ALL_CHANGED" = false ]; then
    echo "✓ 所有文件都是最新的，无需上传"
    echo ""
    echo "💡 提示: 直接回车=重启，输入n=跳过"
    read -p "是否强制重启服务？: " response
    # 回车或输入y/Y都代表确认
    if [[ -z "$response" ]] || [[ "$response" =~ ^[Yy]$ ]]; then
        echo ""
        restart_services
    else
        echo "跳过重启"
    fi
    exit 0
fi

echo "📦 发现 ${#CHANGED_FILES[@]} 个文件有改动"
echo ""

# 上传改动的文件
echo "⬆️  开始上传并备份..."
echo ""

UPLOAD_SUCCESS=true
for file in "${CHANGED_FILES[@]}"; do
    if ! upload_file "$file"; then
        UPLOAD_SUCCESS=false
    fi
done

echo ""

if [ "$UPLOAD_SUCCESS" = false ]; then
    echo "❌ 部分文件上传失败"
    exit 1
fi

echo "✓ 所有文件上传成功！"
echo ""
echo "💾 已备份到: ${BACKUP_PATH}"
echo ""

# Git提交备份目录
git_commit_backup

echo ""

restart_services

echo "================================"
echo "  部署完成！"
echo "================================"
echo ""
echo "🌐 访问地址："
echo "   管理端: http://111.228.8.17:8000/admin.html?admin_token=724caixun_admin_2024_k9HxM7qL"
echo "   Vercel: https://724-cx.vercel.app/admin.html"
echo ""
echo "📂 备份位置: ${BACKUP_PATH}"
echo ""
echo "⚠️  请在浏览器中强制刷新页面 (Ctrl+Shift+R 或 Cmd+Shift+R)"
echo ""
