// @talqora/agent-contracts 的公共入口。
//
// 权威是 proto/ourchat/agent/v1/agent.proto;本包是它经 buf generate(ts-proto,
// onlyTypes)派生的 TS 类型产物,发布到 GitHub Packages 供 web 及未来 TS 消费方使用。
// 不要手改 src/gen/**(由 buf generate 覆写;freshness CI 会校验不漂移)。
export * from './gen/ourchat/agent/v1/agent';
