/* libshim_fcitx_factory — 绕过 QPlatformInputContextFactory::create() 中的 qobject_cast
 *
 * 症状: 双击字幕弹出编辑框后无法输入中文（fcitx5 平台输入上下文加载失败）
 *
 * 根因: PySide6 捆绑的 Qt 6.11 与系统 fcitx5 插件编译的 Qt 6.8 的 staticMetaObject
 *       地址不同 → qobject_cast<QPlatformInputContextPlugin*>() 返回 null
 *
 * 解决: LD_PRELOAD 拦截 create(const QString&) 方法，原实现返回 null 时，
 *       手动创建 QFactoryLoader + static_cast 绕过多态检查。
 *
 * 设计: 只使用 Qt 公开头文件，手工声明私有类型。
 *       QFactoryLoader 的构造函数来自 libQt6Core 运行时（已加载），
 *       因此即使没有 MOC 生成的 QMetaObject，构造和普通方法调用也正常工作。
 *
 * 编译:
 *   g++ -shared -fPIC -std=c++17 \
 *       -I/usr/include/x86_64-linux-gnu/qt6 \
 *       -I/usr/include/x86_64-linux-gnu/qt6/QtCore \
 *       -I/usr/include/x86_64-linux-gnu/qt6/QtGui \
 *       -o libshim_fcitx_factory.so libshim_fcitx_factory.cpp \
 *       -lQt6Core -lQt6Gui -ldl -Wall
 */
#include <dlfcn.h>

#include <QObject>
#include <QString>
#include <QStringList>

/* ── 前向声明（避免 QPA 私有头文件） ──────────────────── */
class QPlatformInputContext;


/* ── 手工声明 QFactoryLoader 接口 ──────────────────────
 * 我们不使用 MOC，因为：
 *   1) 不涉及 signal/slot
 *   2) 构造函数调用会解析到 libQt6Core 中的真实符号
 *   3) staticMetaObject 不对齐也没关系——从不对它做 qobject_cast */
class QFactoryLoader : public QObject {
public:
    explicit QFactoryLoader(const char *iid,
                            const QString &suffix = QString(),
                            Qt::CaseSensitivity cs = Qt::CaseSensitive);
    int indexOf(const QString &needle) const;
    QObject *instance(int index) const;
};


/* ── 手工声明 QPlatformInputContextPlugin 接口 ───────────
 * vtable 布局必须与 Qt 6.8 的编译标准匹配。
 * QObject 虚函数 × 5 + QPlatformInputContextPlugin::create × 1 */
class QPlatformInputContextPlugin : public QObject {
public:
    virtual ~QPlatformInputContextPlugin() = default;
    virtual QPlatformInputContext *create(const QString &key,
                                          const QStringList &paramList) = 0;
};


/* IID 常量 — 和 Qt 源码中 QPlatformInputContextFactoryInterface_iid 一致 */
static const char kIID[] = "org.qt-project.Qt.QPlatformInputContextFactoryInterface.5.1";


/* 原始 QPlatformInputContextFactory::create(const QString&) 类型 */
typedef QPlatformInputContext* (*OrigCreateFn)(const QString&);


/* ── 拦截函数 ─────────────────────────────────────────── */
extern "C" QPlatformInputContext*
_ZN28QPlatformInputContextFactory6createERK7QString(const QString& key)
{
    /* 1) 首次获取原函数地址 */
    static OrigCreateFn orig = nullptr;
    if (!orig) {
        orig = (OrigCreateFn)dlsym(RTLD_NEXT,
            "_ZN28QPlatformInputContextFactory6createERK7QString");
        if (!orig) {
            /* dlsym 失败不可能发生（libQt6Gui 已被加载），不做 fallback */
            return nullptr;
        }
    }

    /* 2) 先尝试原实现 */
    QPlatformInputContext* ctx = orig(key);
    if (ctx)
        return ctx;


    /* 3) 原实现返回 null → static_cast 替代 qobject_cast 绕过多态检查
     *
     * heap 分配 + 永不 delete 是有意的：编译器生成的 ~QFactoryLoader()
     * 与 libQt6Core 的真实析构函数冲突会导致递归，故避免析构。 */
    static QFactoryLoader* s_loader = nullptr;
    if (!s_loader)
        s_loader = new QFactoryLoader(kIID);

    int idx = s_loader->indexOf(key);
    if (idx < 0)
        return nullptr;

    QObject* obj = s_loader->instance(idx);
    if (!obj)
        return nullptr;

    auto* plugin = static_cast<QPlatformInputContextPlugin*>(obj);
    ctx = plugin->create(key, QStringList());
    return ctx;
}
