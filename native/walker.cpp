// Parallel Win32 directory walker -- the StorageAnalyzer hotpath.
//
// Exposes a single pybind11 module, `_native_walker`, with one function
// `walk(root, threads, include_hidden, top_n)` that returns the SAME columnar
// dict the pure-Python fallback returns -- so aggregate/report are walker-
// agnostic. The one difference: this walker fills `dir_recursive` itself and
// sets `recursive_filled=True`.
//
// Speed comes from FindFirstFileExW with FindExInfoBasic +
// FIND_FIRST_EX_LARGE_FETCH: file sizes and attributes arrive *inside* the
// enumeration result, so there is no per-file stat syscall. That, plus a
// worker pool draining a shared job queue, is the whole design.

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

namespace {

struct DirRecord {
    std::wstring path;          // display path (no \\?\ prefix)
    int64_t own = 0;            // bytes of files directly in this directory
    int64_t recursive = 0;      // bytes including all descendants
    int64_t files = 0;          // count of files directly in this directory
    int parent = -1;            // index into the records deque, -1 for root
    int depth = 0;
    bool denied = false;
};

struct DirJob {
    int index;                  // slot in `records` this job fills
    std::wstring real_path;     // \\?\-prefixed path used for enumeration
};

struct FileEntry {
    std::wstring path;
    int64_t size;
};

// Fixed-capacity max-by-eviction min-heap of the largest files seen.
struct TopFiles {
    size_t capacity;
    std::vector<FileEntry> heap;  // min-heap on size

    explicit TopFiles(size_t cap) : capacity(cap ? cap : 1) {}

    static bool cmp(const FileEntry& a, const FileEntry& b) {
        return a.size > b.size;  // std::*_heap with this gives a MIN-heap
    }

    void offer(const std::wstring& path, int64_t size) {
        if (size <= 0) return;
        if (heap.size() < capacity) {
            heap.push_back({path, size});
            std::push_heap(heap.begin(), heap.end(), cmp);
        } else if (!heap.empty() && size > heap.front().size) {
            std::pop_heap(heap.begin(), heap.end(), cmp);
            heap.back() = {path, size};
            std::push_heap(heap.begin(), heap.end(), cmp);
        }
    }
};

constexpr DWORD kReparse = FILE_ATTRIBUTE_REPARSE_POINT;
constexpr DWORD kHidden = FILE_ATTRIBUTE_HIDDEN;
constexpr DWORD kSystem = FILE_ATTRIBUTE_SYSTEM;

std::wstring long_path(const std::wstring& p) {
    if (p.rfind(L"\\\\?\\", 0) == 0) return p;
    if (p.rfind(L"\\\\", 0) == 0) return L"\\\\?\\UNC\\" + p.substr(2);
    return L"\\\\?\\" + p;
}

std::wstring display_path(const std::wstring& p) {
    if (p.rfind(L"\\\\?\\UNC\\", 0) == 0) return L"\\\\" + p.substr(8);
    if (p.rfind(L"\\\\?\\", 0) == 0) return p.substr(4);
    return p;
}

std::string narrow(const std::wstring& w) {
    if (w.empty()) return {};
    int len = WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(),
                                  nullptr, 0, nullptr, nullptr);
    std::string out(len, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(),
                        out.data(), len, nullptr, nullptr);
    return out;
}

class Walker {
public:
    Walker(std::wstring root, int threads, bool include_hidden, size_t top_n)
        : include_hidden_(include_hidden), top_n_(top_n) {
        unsigned hw = std::thread::hardware_concurrency();
        if (hw == 0) hw = 4;
        int clamped = (int)std::min<unsigned>(16u, std::max<unsigned>(2u, hw));
        thread_count_ = threads > 0 ? threads : clamped;

        std::wstring real_root = long_path(root);
        records_.push_back(DirRecord{display_path(real_root), 0, 0, 0, -1, 0, false});
        jobs_.push_back(DirJob{0, real_root});
    }

    void run() {
        std::vector<std::thread> pool;
        std::vector<TopFiles> local_tops;
        local_tops.reserve(thread_count_);
        for (int i = 0; i < thread_count_; ++i) local_tops.emplace_back(top_n_);

        for (int i = 0; i < thread_count_; ++i) {
            pool.emplace_back(&Walker::worker, this, std::ref(local_tops[i]));
        }
        for (auto& t : pool) t.join();

        // Merge thread-local heaps into one globally-largest list.
        for (auto& tf : local_tops) {
            for (auto& fe : tf.heap) merged_top_.push_back(fe);
        }
        std::sort(merged_top_.begin(), merged_top_.end(),
                  [](const FileEntry& a, const FileEntry& b) {
                      return a.size > b.size;
                  });
        if (merged_top_.size() > top_n_) merged_top_.resize(top_n_);

        // Records were appended BFS (parents before children), so a single
        // reverse pass rolls every child's recursive size into its parent.
        for (auto& r : records_) r.recursive = r.own;
        for (size_t i = records_.size(); i-- > 0;) {
            int p = records_[i].parent;
            if (p >= 0) records_[p].recursive += records_[i].recursive;
        }
    }

    py::dict to_dict() {
        py::list dir_path, dir_own, dir_recursive, dir_files;
        py::list dir_parent, dir_depth, dir_denied;
        int64_t total_bytes = 0, total_files = 0;
        int denied_count = 0;

        for (auto& r : records_) {
            dir_path.append(py::str(narrow(r.path)));
            dir_own.append(r.own);
            dir_recursive.append(r.recursive);
            dir_files.append(r.files);
            dir_parent.append(r.parent);
            dir_depth.append(r.depth);
            dir_denied.append(r.denied);
            total_bytes += r.own;
            total_files += r.files;
            if (r.denied) ++denied_count;
        }

        py::list top_files;
        for (auto& fe : merged_top_) {
            top_files.append(py::make_tuple(py::str(narrow(fe.path)), fe.size));
        }

        py::dict stats;
        stats["files_scanned"] = total_files;
        stats["dirs_scanned"] = (int64_t)records_.size();
        stats["total_bytes"] = total_bytes;
        stats["denied_count"] = denied_count;
        stats["threads"] = thread_count_;

        py::dict out;
        out["dir_path"] = dir_path;
        out["dir_own"] = dir_own;
        out["dir_recursive"] = dir_recursive;
        out["dir_files"] = dir_files;
        out["dir_parent"] = dir_parent;
        out["dir_depth"] = dir_depth;
        out["dir_denied"] = dir_denied;
        out["top_files"] = top_files;
        out["stats"] = stats;
        out["recursive_filled"] = true;
        return out;
    }

private:
    bool is_hidden(DWORD attrs) const {
        return (attrs & (kHidden | kSystem)) != 0;
    }

    void process(int index, const std::wstring& real_path, TopFiles& tops) {
        std::wstring pattern = real_path;
        if (!pattern.empty() && pattern.back() != L'\\') pattern += L'\\';
        pattern += L'*';

        WIN32_FIND_DATAW fd;
        HANDLE h = FindFirstFileExW(pattern.c_str(), FindExInfoBasic, &fd,
                                    FindExSearchNameMatch, nullptr,
                                    FIND_FIRST_EX_LARGE_FETCH);
        if (h == INVALID_HANDLE_VALUE) {
            DWORD err = GetLastError();
            if (err == ERROR_ACCESS_DENIED) {
                std::lock_guard<std::mutex> lk(mtx_);
                records_[index].denied = true;
            }
            // ERROR_FILE_NOT_FOUND etc. -- treat as an empty directory.
            return;
        }

        int64_t own = 0, files = 0;
        int depth = records_[index].depth;  // immutable after creation
        struct PendingChild { std::wstring real, display; };
        std::vector<PendingChild> children;

        do {
            const wchar_t* name = fd.cFileName;
            if (name[0] == L'.' &&
                (name[1] == L'\0' || (name[1] == L'.' && name[2] == L'\0'))) {
                continue;  // skip "." and ".."
            }
            DWORD attrs = fd.dwFileAttributes;
            if (!include_hidden_ && is_hidden(attrs)) continue;

            bool is_reparse = (attrs & kReparse) != 0;
            bool is_dir = (attrs & FILE_ATTRIBUTE_DIRECTORY) != 0;

            std::wstring child_real = pattern;
            child_real.pop_back();          // drop the '*'
            child_real += name;

            if (is_dir && !is_reparse) {
                children.push_back({child_real, display_path(child_real)});
            } else {
                // files, plus reparse points / symlinked dirs as leaves
                int64_t size =
                    ((int64_t)fd.nFileSizeHigh << 32) | fd.nFileSizeLow;
                own += size;
                ++files;
                tops.offer(display_path(child_real), size);
            }
        } while (FindNextFileW(h, &fd));
        FindClose(h);

        // One critical section per directory: commit own totals, reserve
        // child record slots (so parent linkage is final), enqueue jobs.
        {
            std::lock_guard<std::mutex> lk(mtx_);
            records_[index].own = own;
            records_[index].files = files;
            for (auto& c : children) {
                int child_idx = (int)records_.size();
                records_.push_back(
                    DirRecord{c.display, 0, 0, 0, index, depth + 1, false});
                jobs_.push_back(DirJob{child_idx, c.real});
            }
        }
        if (!children.empty()) cv_.notify_all();
    }

    void worker(TopFiles& tops) {
        for (;;) {
            DirJob job;
            {
                std::unique_lock<std::mutex> lk(mtx_);
                cv_.wait(lk, [this] {
                    return !jobs_.empty() || active_ == 0;
                });
                if (jobs_.empty()) {
                    // No work queued and nobody mid-job: walk is complete.
                    cv_.notify_all();
                    return;
                }
                job = jobs_.back();
                jobs_.pop_back();
                ++active_;
            }
            process(job.index, job.real_path, tops);
            {
                std::lock_guard<std::mutex> lk(mtx_);
                --active_;
                if (active_ == 0 && jobs_.empty()) cv_.notify_all();
            }
        }
    }

    bool include_hidden_;
    size_t top_n_;
    int thread_count_;

    std::mutex mtx_;
    std::condition_variable cv_;
    std::deque<DirRecord> records_;   // stable refs on growth; BFS order
    std::deque<DirJob> jobs_;
    int active_ = 0;

    std::vector<FileEntry> merged_top_;
};

py::dict walk(const std::wstring& root, int threads, bool include_hidden,
              size_t top_n) {
    Walker walker(root, threads, include_hidden, top_n);
    {
        // The scan is pure Win32 I/O -- release the GIL so it does not block
        // the interpreter, and so the worker threads genuinely overlap.
        py::gil_scoped_release release;
        walker.run();
    }
    return walker.to_dict();
}

}  // namespace

PYBIND11_MODULE(_native_walker, m) {
    m.doc() = "Parallel Win32 directory walker for StorageAnalyzer.";
    m.def("walk", &walk,
          py::arg("root"),
          py::arg("threads") = 0,
          py::arg("include_hidden") = false,
          py::arg("top_n") = 50,
          "Walk a directory tree in parallel; returns the columnar dict "
          "contract shared with the pure-Python fallback walker.");
}
