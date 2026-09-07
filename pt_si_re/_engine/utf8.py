# -*- coding: utf-8 -*-
"""한글 출력이 locale 때문에 죽지 않게 만든다.

왜 필요한가
    이 패키지의 화면 출력은 전부 한국어다. 그런데 파이썬은 stdout 인코딩을
    **환경의 locale** 에서 가져온다. EDA 서버는 `LANG` 이 없거나 `C` / `POSIX`
    인 경우가 흔하고, 그러면 인코딩이 ascii 가 되어 첫 한글 줄에서 죽는다.

        UnicodeEncodeError: 'ascii' codec can't encode characters

    파이썬 3.7+ 는 알아서 UTF-8 로 넘어가지만, 우리가 현장에서 쓰라고 안내하는
    PrimeTime 번들 파이썬은 **3.6.10** 이라 그 보호가 없다. 즉 제일 흔한 조합에서
    터진다.

    그래서 시작할 때 stdout/stderr 를 UTF-8 로 감싼다. 이미 UTF-8 이면 아무것도
    하지 않는다. 파이썬 2 에서도 동작한다.

쓰는 법
    각 스크립트 맨 위에서 한 번:
        from utf8 import force_utf8
        force_utf8()
"""
import os
import sys


def force_utf8():
    """stdout/stderr 를 UTF-8 로 맞춘다. 이미 UTF-8 이면 그대로 둔다.

    파이썬 2 에서는 아무것도 하지 않는다. 2 의 문자열은 이미 utf-8 바이트라
    그대로 써도 locale 과 무관하게 잘 나간다. 오히려 codecs 로 감싸면 파이썬이
    그 바이트를 ascii 로 **디코딩**하려 들어 죽는다.
        UnicodeDecodeError: 'ascii' codec can't decode byte 0xed
    """
    if sys.version_info[0] < 3:
        return
    enc = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "")

    # 'backslashreplace' 를 쓰는 이유
    #     입력 파일을 errors="surrogateescape" 로 읽으므로, 넷 이름에 UTF-8 이
    #     아닌 바이트가 있으면 그것이 \udcXX 형태로 문자열에 남는다. 그 이름을
    #     화면에 찍으려 하면 기본(strict) 처리에서 죽는다.
    #         UnicodeEncodeError: 'utf-8' codec can't encode character '\udcb5'
    #     backslashreplace 는 죽지 않으면서 어떤 바이트였는지도 보여 준다.
    if "utf8" in enc:
        # 이미 UTF-8 이라 인코딩은 맞다. 오류 처리만 느슨하게 바꾼다.
        try:
            sys.stdout.reconfigure(errors="backslashreplace")   # 3.7+
            sys.stderr.reconfigure(errors="backslashreplace")
            return
        except Exception:
            pass                                               # 3.6 -> 아래에서 감싼다
    try:
        import codecs
        writer = codecs.getwriter("utf-8")
        # 파이썬 3 은 .buffer(바이트 스트림)를 감싸야 한다. 2 는 stdout 자체가
        # 바이트 스트림이라 그대로 감싼다.
        out = getattr(sys.stdout, "buffer", sys.stdout)
        err = getattr(sys.stderr, "buffer", sys.stderr)
        sys.stdout = writer(out, "backslashreplace")
        sys.stderr = writer(err, "backslashreplace")
    except Exception:
        # 여기서 실패해도 스크립트 자체는 계속 가야 한다.
        pass


class _AtomicWrite(object):
    """다 쓴 뒤에야 그 이름이 생기게 한다.

    왜 필요한가
        코너를 돌리다 Ctrl-C 나 종료로 끊기면, 그때까지 쓰인 반쪽 파일이
        **최종 이름 그대로** 남는다. 그다음 --skip-done 으로 이어서 돌리면
        그 반쪽을 완성품으로 보고 건너뛴다. 깨진 값이 조용히 뒤 단계로
        넘어가고, 한참 뒤 모델이 이상할 때야 알게 된다.

        그래서 옆에 <이름>.part 로 쓰고, 끝까지 잘 쓰였을 때만 제자리로
        옮긴다. rename 은 같은 폴더 안에서는 원자적이라 중간 상태가 없다.
        끊기면 .part 만 남고 최종 이름은 안 생기므로, 다시 돌릴 때 그 단계가
        제대로 다시 돈다.
    """

    def __init__(self, path):
        self.path = path
        self.tmp = path + ".part"
        self.fh = None

    def __enter__(self):
        import io
        if sys.version_info[0] >= 3:
            # 읽을 때 surrogateescape 로 살려 둔 바이트를 그대로 써낸다.
            # 이것이 없으면 "surrogates not allowed" 로 쓰기에서 죽는다.
            self.fh = io.open(self.tmp, "w", encoding="utf-8",
                              errors="surrogateescape")
        else:
            self.fh = open(self.tmp, "w")
        return self.fh

    def __exit__(self, exc_type, exc, tb):
        self.fh.close()
        if exc_type is not None:
            # 실패했으면 .part 를 치운다. 최종 이름은 건드리지 않았으므로
            # 예전 결과가 있었다면 그대로 남는다.
            try:
                os.remove(self.tmp)
            except OSError:
                pass
            return False
        os.rename(self.tmp, self.path)
        return False


def wopen(path):
    """한글이 들어가는 파일을 쓸 때 쓴다. locale 과 무관하게 UTF-8 로 저장한다.

    파이썬 3 의 내장 open 도 인코딩을 locale 에서 가져오므로, LANG 이 C 이면
    파일에 한글을 쓸 때 UnicodeEncodeError 로 죽는다(화면 출력과 같은 문제).
    파이썬 2 에서는 문자열이 이미 utf-8 바이트라 내장 open 이 맞다.

    **반드시 with 로 쓴다.** 다 쓴 뒤에야 그 이름이 생긴다(위 _AtomicWrite).
    """
    return _AtomicWrite(path)
