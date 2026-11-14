"""Local CLI boundary. Credentials go directly from a private file to child stdin."""
from contextlib import ExitStack
from pathlib import Path
import json
import os
import shutil
import stat
import subprocess


class WeChatReadError(RuntimeError):
    def __init__(self,code='localReadFailed'):
        self.code=code
        super().__init__('本地微信读取未完成（'+code+'）；没有发送给模型。')


class GreenBubbles:
    def __init__(self,binary=None,source_root=None,credential_file=None,*,decrypted=False):
        self.binary=binary or os.getenv('CHIGUA_WECHAT_BIN') or shutil.which('greenbubbles')
        if not self.binary:raise ValueError('尚未安装并初始化 GreenBubbles；本程序不会自行获取密钥或修改微信。')
        self.source_root=Path(source_root).resolve() if source_root else None
        self.credential_file=Path(credential_file) if credential_file else None
        self.decrypted=decrypted
        if decrypted and (not source_root or credential_file):raise ValueError('明文测试源必须明确指定，且不能同时使用凭据。')
        if bool(source_root)!=bool(credential_file) and not decrypted:
            raise ValueError('指定数据库目录时必须同时指定私有凭据文件。')

    def run(self,command,*,timeout=60):
        split=3 if command[:2] in [['chats','find'],['conversations','find']] else 2
        args=[str(self.binary),*command[:split]]
        if self.source_root:args.append(str(self.source_root))
        args.extend(command[split:])
        with ExitStack() as stack:
            kwargs={}
            if self.credential_file:
                # Do not read credentials into Python strings, prompts, argv or logs.
                try:
                    fd=os.open(self.credential_file,os.O_RDONLY|os.O_NOFOLLOW)
                    handle=stack.enter_context(os.fdopen(fd,'rb'))
                    info=os.fstat(handle.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
                        raise ValueError('凭据必须为当前用户所有、仅本人可读的普通文件。')
                except OSError:raise ValueError('无法打开本机私有凭据文件。') from None
                kwargs['stdin']=handle;args.append('--passphrase-stdin')
            elif self.decrypted:args.append('--decrypted')
            try:result=subprocess.run(args,capture_output=True,text=True,timeout=timeout,**kwargs)
            except (OSError,subprocess.TimeoutExpired):raise WeChatReadError('unavailableOrTimeout') from None
        if len(result.stdout.encode())>8*1024*1024:raise ValueError('本地工具响应超过大小限制。')
        try:value=json.loads(result.stdout)
        except ValueError:raise WeChatReadError() from None
        if result.returncode or (isinstance(value,dict) and value.get('ok') is False):
            code=value.get('error',{}).get('code') if isinstance(value,dict) else None
            allowed={'attachmentUnavailable','sourceChanged','decodeFailed','outputRejected','unsafeSource','invalidArgument'}
            raise WeChatReadError(code if code in allowed else 'localReadFailed')
        return value
