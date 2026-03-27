import os, sys, re, json, argparse, time, configparser
from pathlib import Path
from urllib import request, parse, error
from datetime import datetime, timezone

CONFIG_PATH = Path(__file__).parent / 'config.ini'

P401 = re.compile(r'(^|\D)401(\D|$)|unauthorized|unauthenticated|token\s+expired|login\s+required|authentication\s+failed', re.I)
PQUOTA = re.compile(r'(^|\D)(402|403|429)(\D|$)|quota|insufficient\s*quota|resource\s*exhausted|rate\s*limit|too\s+many\s+requests|payment\s+required|billing|credit|额度|用完|超限|上限|usage_limit_reached', re.I)

def get_current_time():
    return datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z')

def run_id():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

def api(base, key, method, path, timeout=20, query=None, expect_json=True, body=None):
    url = base.rstrip('/') + '/v0/management' + path
    if query:
        url += '?' + parse.urlencode(query)
    headers = {
        'Authorization': 'Bearer ' + key,
        'Accept': 'application/json',
        'User-Agent': 'cliproxyapi-cleaner/1.0',
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = request.Request(
        url,
        data=data,
        headers=headers,
        method=method.upper()
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.getcode()
    except error.HTTPError as e:
        raw = e.read()
        code = e.code
    except error.URLError as e:
        raise RuntimeError('请求管理 API 失败: %s' % e)

    if expect_json:
        try:
            payload = json.loads(raw.decode('utf-8')) if raw else {}
        except Exception:
            payload = {'raw': raw.decode('utf-8', errors='replace')}
        return code, payload
    return code, raw

def extract_error_message(msg):
    """从状态消息中提取错误信息"""
    try:
        if isinstance(msg, str) and msg.strip().startswith('{'):
            error_data = json.loads(msg)
            if 'error' in error_data:
                error_obj = error_data['error']
                if isinstance(error_obj, dict):
                    error_type = error_obj.get('type', '')
                    error_message = error_obj.get('message', '')
                    return error_type, error_message
                elif isinstance(error_obj, str):
                    return 'error', error_obj
            return None, msg
    except:
        pass
    return None, msg

def classify(item):
    status = str(item.get('status', '')).strip().lower()
    msg = str(item.get('status_message', '') or '').strip()
    
    error_type, error_msg = extract_error_message(msg)
    text = (status + '\n' + msg).lower()
    
    # 1. 检查 401 认证错误（这些会被删除）
    if P401.search(text):
        return 'delete_401', msg or status or '401/unauthorized'
    
    # 2. 检查 usage_limit_reached（配额耗尽，不删除）
    if error_type == 'usage_limit_reached' or 'usage_limit_reached' in text:
        return 'quota_exhausted', msg or status or 'usage_limit_reached'
    
    # 3. 检查其他配额相关错误（不删除）
    if PQUOTA.search(text):
        return 'quota_exhausted', msg or status or 'quota'
    
    # 4. 检查禁用状态（不删除）
    if bool(item.get('disabled', False)) or status == 'disabled':
        return 'disabled', msg or status or 'disabled'
    
    # 5. 检查不可用状态（不删除）
    if bool(item.get('unavailable', False)) or status == 'error':
        return 'unavailable', msg or status or 'error'
    
    return 'available', msg or status or 'active'

def run_check(args):
    """执行一次检查"""
    code, payload = api(args.base_url, args.management_key, 'GET', '/auth-files', args.timeout)
    if code != 200:
        print('[错误] 获取 auth-files 失败: HTTP %s %s' % (code, payload), file=sys.stderr)
        return None

    files = payload.get('files') or []
    if not isinstance(files, list):
        print('[错误] auth-files 返回异常: %s' % payload, file=sys.stderr)
        return None

    rid = run_id()
    backup_root = Path('./backups/cliproxyapi-auth-cleaner') / rid
    report_root = Path('./reports/cliproxyapi-auth-cleaner')
    report_root.mkdir(parents=True, exist_ok=True)

    counts = {
        '检查总数': 0,
        '可用账号': 0,
        '配额耗尽': 0,
        '已禁用': 0,
        '不可用': 0,
        '待删除': 0,
        '已删除': 0,
        '备份失败': 0,
        '删除失败': 0,
    }
    results = []

    print('[%s] 开始检查 %s 个账号' % (get_current_time(), len(files)), flush=True)

    for item in files:
        counts['检查总数'] += 1
        name = str(item.get('name') or item.get('id') or '').strip()
        provider = str(item.get('provider') or item.get('type') or '').strip()
        kind, reason = classify(item)
        
        # 简化 reason 显示
        display_reason = reason
        if reason and reason.strip().startswith('{'):
            try:
                error_data = json.loads(reason)
                if 'error' in error_data:
                    error_obj = error_data['error']
                    if isinstance(error_obj, dict):
                        error_type = error_obj.get('type', '')
                        error_message = error_obj.get('message', '')
                        if error_type == 'usage_limit_reached':
                            display_reason = f'usage_limit_reached: {error_message[:50]}'
                        else:
                            display_reason = error_type or error_message[:50]
                    else:
                        display_reason = str(error_obj)[:50]
            except:
                display_reason = reason[:50]

        row = {
            'name': name,
            'provider': provider,
            'auth_index': item.get('auth_index'),
            'status': item.get('status'),
            'status_message': item.get('status_message'),
            'final_classification': kind,
            'reason': reason,
        }

        # 根据不同分类输出信息
        if kind == 'available':
            counts['可用账号'] += 1
            # 不输出可用账号，保持输出简洁

        elif kind == 'unavailable':
            counts['不可用'] += 1
            print('[不可用-不删除] %s provider=%s reason=%s' % (name, provider, display_reason), flush=True)

        elif kind in ('delete_401', 'quota_exhausted', 'disabled'):
            # 401、配额耗尽、已禁用 统一执行备份删除
            label_map = {
                'delete_401': ('待删除-401认证失败', '待删除'),
                'quota_exhausted': ('待删除-配额耗尽', '配额耗尽'),
                'disabled': ('待删除-已禁用', '已禁用'),
            }
            label, count_key = label_map[kind]
            counts[count_key] += 1
            counts['待删除'] += 1
            print('[%s] %s provider=%s reason=%s' % (label, name, provider, display_reason), flush=True)

            if args.dry_run:
                row['delete_result'] = 'dry_run_skip'
                print('  [模拟运行] 将删除此账号', flush=True)
            else:
                if not name.lower().endswith('.json'):
                    counts['删除失败'] += 1
                    row['delete_result'] = 'skip_no_json_name'
                    row['delete_error'] = '不是标准 .json 文件名，默认不删'
                    print('  [跳过] 不是 .json 文件', flush=True)
                else:
                    try:
                        code, raw = api(args.base_url, args.management_key, 'GET', '/auth-files/download', args.timeout, {'name': name}, False)
                        if code != 200:
                            raise RuntimeError('下载 auth 文件失败: %s HTTP %s' % (name, code))
                        backup_root.mkdir(parents=True, exist_ok=True)
                        backup_path = backup_root / Path(name).name
                        backup_path.write_bytes(raw)
                        row['backup_path'] = str(backup_path)

                        code, payload = api(args.base_url, args.management_key, 'DELETE', '/auth-files', args.timeout, {'name': name}, True)
                        if code != 200:
                            raise RuntimeError('删除 auth 文件失败: %s HTTP %s %s' % (name, code, payload))
                        counts['已删除'] += 1
                        row['delete_result'] = 'deleted'
                        row['delete_response'] = payload
                        print('  [已删除] 备份路径: %s' % row['backup_path'], flush=True)
                    except Exception as e:
                        counts['删除失败'] += 1
                        row['delete_result'] = 'delete_failed'
                        row['delete_error'] = str(e)
                        print('  [删除失败] %s' % e, flush=True)
        
        results.append(row)

    report = {
        'run_id': rid,
        'base_url': args.base_url,
        'dry_run': args.dry_run,
        'results': results,
        'summary': counts,
    }
    report_path = report_root / ('report-' + rid + '.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    # 输出统计信息
    print('\n' + '='*60)
    print('【统计结果】')
    print('='*60)
    for key, value in counts.items():
        print('  %s: %d' % (key, value))
    
    print('\n【操作说明】')
    if args.dry_run:
        print('  ✅ 模拟运行模式 - 没有实际删除任何账号')
        if counts['待删除'] > 0:
            details = []
            for key in ('配额耗尽', '已禁用'):
                if counts[key] > 0:
                    details.append('%s: %d' % (key, counts[key]))
            other = counts['待删除'] - counts['配额耗尽'] - counts['已禁用']
            if other > 0:
                details.append('401: %d' % other)
            print('  📝 发现 %d 个待删除账号（%s）' % (counts['待删除'], ', '.join(details)))
            print('  📝 如需执行请去掉 --dry-run 参数')
    else:
        if counts['已删除'] > 0:
            print('  ✅ 已删除 %d 个账号' % counts['已删除'])
        else:
            print('  ℹ️  未发现需要删除的账号')
        if counts['删除失败'] > 0:
            print('  ⚠️  有 %d 个账号删除失败，请查看报告' % counts['删除失败'])
    
    print('\n【报告文件】')
    print('  📄 %s' % report_path)
    print('='*60, flush=True)
    
    return counts

def load_config():
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(str(CONFIG_PATH), encoding='utf-8')
    section = 'cliproxyapi'
    return {
        'base_url': cfg.get(section, 'base-url', fallback=''),
        'management_key': cfg.get(section, 'management-key', fallback=''),
    }

def main():
    defaults = load_config()
    ap = argparse.ArgumentParser(description='CLIProxyAPI 清理工具 - 删除 401、配额耗尽和已禁用的账号')
    ap.add_argument('--base-url', default=defaults['base_url'])
    ap.add_argument('--management-key', default=defaults['management_key'])
    ap.add_argument('--timeout', type=int, default=int(os.environ.get('CLIPROXY_TIMEOUT', '20')))
    ap.add_argument('--dry-run', action='store_true', help='模拟运行，不实际删除')
    ap.add_argument('--interval', type=int, default=60, help='检测间隔时间（秒），默认60秒')
    ap.add_argument('--once', action='store_true', help='只执行一次，不循环')
    args = ap.parse_args()

    if not args.management_key.strip():
        print('❌ 缺少 management key：请先设置 CLIPROXY_MANAGEMENT_KEY', file=sys.stderr)
        return 2

    print('\n' + '='*60)
    print('【CLIProxyAPI 清理工具】')
    print('='*60)
    print('  🎯 清理目标: 删除 401、配额耗尽和已禁用的账号')
    print('  🛡️  保护机制: 不可用账号不会被操作')
    if args.dry_run:
        print('  🔍 运行模式: 模拟运行（不会实际删除）')
    else:
        print('  ⚡ 运行模式: 实际运行（将删除符合条件的账号）')
    print('='*60 + '\n')

    if args.once:
        run_check(args)
        return 0
    
    # 循环执行
    print('🔄 自动循环检测模式，间隔 %d 秒' % args.interval)
    print('💡 提示: 按 Ctrl+C 停止程序\n')
    
    loop_count = 0
    try:
        while True:
            loop_count += 1
            print('\n' + '🔵'*30)
            print('【第 %d 次检测】%s' % (loop_count, get_current_time()))
            print('🔵'*30)
            
            try:
                counts = run_check(args)
            except Exception as e:
                print('❌ 检测过程中发生异常: %s' % e, flush=True)
            
            print('\n⏰ 等待 %d 秒后进行下一次检测...' % args.interval)
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print('\n\n🛑 用户中断程序，共执行 %d 次检测' % loop_count)
        return 0

if __name__ == '__main__':
    raise SystemExit(main())