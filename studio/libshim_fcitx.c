/* libshim_fcitx — 补齐 fcitx5 Qt6 插件在 PySide6 Qt 下缺失的符号
 *
 * 症状: fcitx5 Qt6 平台输入上下文插件无法加载，错误为
 *   libQt6WaylandClient.so.6: undefined symbol: _ZTI20QGenericUnixServices
 *
 * 原因: fcitx5 插件链接了系统 libQt6WaylandClient.so.6，该库引用了
 *   QGenericUnixServices 类型信息（来自 libQt6Gui.so.6）。
 *   PySide6 捆绑的 Qt6 版本较新（6.11+），已移除该私有 API 符号。
 *   在 X11 下该符号从不被执行到，但动态链接器在 dlopen 时仍需要它。
 *
 * 解决: LD_PRELOAD 此 shim，提供空存根满足链接器即可。
 * 版本标签: 配合 libshim_fcitx.ver 为所有符号添加 @Qt_6_PRIVATE_API 版本标签，
 *   与 libQt6WaylandClient.so.6 中的引用精确匹配。
 *
 * 构建:
 *   gcc -shared -fPIC -o libshim_fcitx.so libshim_fcitx.c \
 *       -Wl,--version-script=libshim_fcitx.ver -Wall
 */
#include <stddef.h>

/* typeinfo / vtable / type-string — 只用于链接，运行时永不触及 */
void *_ZTI20QGenericUnixServices = NULL;
void *_ZTS20QGenericUnixServices = "";
void *_ZTV20QGenericUnixServices = NULL;

/* 虚函数/普通成员存根 */
void _ZN20QGenericUnixServicesC1Ev(void) { }
void _ZN20QGenericUnixServicesC2Ev(void) { }
void _ZN20QGenericUnixServicesD1Ev(void) { }
void _ZN20QGenericUnixServicesD2Ev(void) { }
void _ZN20QGenericUnixServicesD0Ev(void) { }
void _ZN20QGenericUnixServices11colorPickerEP7QWindow(void) { }
void _ZN20QGenericUnixServices12openDocumentERK4QUrl(void) { }
void _ZN20QGenericUnixServices19setApplicationBadgeEx(void) { }
void _ZN20QGenericUnixServices22portalWindowIdentifierEP7QWindow(void) { }
void _ZN20QGenericUnixServices7openUrlERK4QUrl(void) { }
void _ZNK20QGenericUnixServices13hasCapabilityEN17QPlatformServices10CapabilityE(void) { }
void _ZNK20QGenericUnixServices18desktopEnvironmentEv(void) { }
