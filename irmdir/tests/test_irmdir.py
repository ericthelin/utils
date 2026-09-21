#!/usr/bin/env python3
import os
import subprocess
import tempfile
import shutil
import sys

IRMDIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'irmdir'))

failed = []

def run_cmd(args, cwd=None, capture_output=True):
    cp = subprocess.run([IRMDIR] + args, stdout=subprocess.PIPE if capture_output else None,
                        stderr=subprocess.PIPE if capture_output else None, text=True, cwd=cwd)
    return cp


def expect(cond, name, info=''):
    if not cond:
        failed.append((name, info))
        print(f"[FAIL] {name}: {info}")
    else:
        print(f"[OK]  {name}")


def test_empty_dir(tmp):
    d = os.path.join(tmp, 'empty')
    os.makedirs(d)
    cp = run_cmd([d])
    expect(cp.returncode == 0, 'empty_dir:exit', f'returncode={cp.returncode}')
    expect(not os.path.exists(d), 'empty_dir:removed', 'directory still exists')


def test_nested_only_dirs(tmp):
    base = os.path.join(tmp, 'nested')
    os.makedirs(os.path.join(base, 'a', 'b', 'c'))
    cp = run_cmd([base])
    expect(cp.returncode == 0, 'nested_only_dirs:exit', f'returncode={cp.returncode}')
    expect(not os.path.exists(base), 'nested_only_dirs:removed', 'base still exists')


def test_dir_with_file(tmp):
    base = os.path.join(tmp, 'withfile')
    os.makedirs(base)
    with open(os.path.join(base, 'file.txt'), 'w') as f:
        f.write('hello')
    cp = run_cmd([base])
    # Implementation should skip removing directories that contain files; expect dir remains
    expect(cp.returncode == 0, 'dir_with_file:exit', f'returncode={cp.returncode}')
    expect(os.path.exists(base), 'dir_with_file:exists', 'directory was removed but should not have been')


def test_parents_behavior(tmp):
    base = os.path.join(tmp, 'parents')
    deep = os.path.join(base, 'a', 'b')
    os.makedirs(deep)
    # Place a file in 'a' so parent removal should stop at 'a'
    with open(os.path.join(base, 'a', 'keep.txt'), 'w') as f:
        f.write('x')
    cp = run_cmd(['-p', deep])
    # b should be removed; a should still exist; returncode non-zero due to rmdir failure on a
    expect(not os.path.exists(deep), 'parents:b_removed', 'b still exists')
    expect(os.path.exists(os.path.join(base, 'a')), 'parents:a_exists', 'a was removed but should remain')
    expect(cp.returncode != 0, 'parents:exit_nonzero', f'returncode={cp.returncode}')


def test_parents_ignore(tmp):
    base = os.path.join(tmp, 'parents_ignore')
    deep = os.path.join(base, 'a', 'b')
    os.makedirs(deep)
    with open(os.path.join(base, 'a', 'keep.txt'), 'w') as f:
        f.write('x')
    cp = run_cmd(['--ignore-fail-on-non-empty', '-p', deep])
    expect(not os.path.exists(deep), 'parents_ignore:b_removed', 'b still exists')
    expect(os.path.exists(os.path.join(base, 'a')), 'parents_ignore:a_exists', 'a was removed but should remain')
    expect(cp.returncode == 0, 'parents_ignore:exit_zero', f'returncode={cp.returncode}')


def test_symlink_to_file(tmp):
    base = os.path.join(tmp, 'symlink_file')
    os.makedirs(base)
    target = os.path.join(tmp, 'target_file.txt')
    with open(target, 'w') as f:
        f.write('x')
    os.symlink(target, os.path.join(base, 'link'))
    cp = run_cmd([base, '-v'])
    # Should skip and not remove directory
    expect(cp.returncode == 0, 'symlink_file:exit', f'returncode={cp.returncode}')
    expect(os.path.exists(base), 'symlink_file:exists', 'directory was removed but should not have been')


def test_symlink_to_dir(tmp):
    base = os.path.join(tmp, 'symlink_dir')
    os.makedirs(base)
    target_dir = os.path.join(tmp, 'target_dir')
    os.makedirs(target_dir)
    os.symlink(target_dir, os.path.join(base, 'linkdir'))
    cp = run_cmd([base])
    # Should skip and not remove directory because it contains a symlink
    expect(cp.returncode == 0, 'symlink_dir:exit', f'returncode={cp.returncode}')
    expect(os.path.exists(base), 'symlink_dir:exists', 'directory was removed but should not have been')


def test_fifo_special_file(tmp):
    base = os.path.join(tmp, 'withfifo')
    os.makedirs(base)
    fifo = os.path.join(base, 'pipe')
    try:
        os.mkfifo(fifo)
    except AttributeError:
        # Windows or unsupported; skip test as fifo not available
        print('skipping fifo test (mkfifo not available)')
        return
    cp = run_cmd([base])
    expect(cp.returncode == 0, 'fifo:exit', f'returncode={cp.returncode}')
    expect(os.path.exists(base), 'fifo:exists', 'directory was removed but should not have been')


def test_permission_block(tmp):
    base = os.path.join(tmp, 'permtest')
    deep = os.path.join(base, 'a', 'b')
    os.makedirs(deep)
    a_dir = os.path.join(base, 'a')
    # Remove write permission on 'a' to prevent removing its child
    orig_mode = os.stat(a_dir).st_mode
    os.chmod(a_dir, 0o500)
    try:
        cp = run_cmd([base])
        # Expect that b is not removed due to permission error
        expect(os.path.exists(deep), 'perm:b_exists', 'b was removed though it should be protected')
        expect(cp.returncode != 0, 'perm:exit_nonzero', f'returncode={cp.returncode}')
    finally:
        # restore perms so cleanup can proceed
        try:
            os.chmod(a_dir, orig_mode)
        except Exception:
            pass


def test_dry_run(tmp):
    base = os.path.join(tmp, 'dryrun')
    os.makedirs(os.path.join(base, 'x', 'y'))
    cp = run_cmd(['--dry-run', '-v', base])
    # Nothing should be removed
    expect(os.path.exists(base), 'dryrun:exists', 'directory was removed during dry-run')
    # Output should mention 'would remove'
    expect('would remove' in (cp.stdout or '') , 'dryrun:output', 'no "would remove" message in output')


def test_nonrecursive_falls_back(tmp):
    base = os.path.join(tmp, 'nonrec')
    os.makedirs(base)
    # create a file so rmdir will fail
    with open(os.path.join(base, 'f.txt'), 'w') as f:
        f.write('x')
    cp = run_cmd(['-D', base])
    # rmdir should return non-zero for non-empty dir
    expect(cp.returncode != 0, 'nonrecursive:exit_nonzero', f'returncode={cp.returncode}')
    expect(os.path.exists(base), 'nonrecursive:exists', 'directory should remain')


def main():
    tmp = tempfile.mkdtemp(prefix='irmdir_test_')
    print('Using tmpdir:', tmp)
    try:
        tests = [
            test_empty_dir,
            test_nested_only_dirs,
            test_dir_with_file,
            test_parents_behavior,
            test_parents_ignore,
            test_symlink_to_file,
            test_symlink_to_dir,
            test_fifo_special_file,
            test_permission_block,
            test_dry_run,
            test_nonrecursive_falls_back,
        ]
        for t in tests:
            print('\n===', t.__name__, '===')
            t(tmp)

        if failed:
            print('\nSUMMARY: Some tests failed:')
            for name, info in failed:
                print('-', name, info)
            sys.exit(2)
        else:
            print('\nSUMMARY: All tests passed')
            sys.exit(0)
    finally:
        try:
            shutil.rmtree(tmp)
        except Exception:
            pass

if __name__ == '__main__':
    main()
