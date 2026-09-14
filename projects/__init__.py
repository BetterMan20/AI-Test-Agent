# projects — 项目适配层（各业务的适配器，含具体业务逻辑；与 Core 引擎解耦）
# Core 通过 core.adapters.registry 动态加载，绝不直接 import 这里。