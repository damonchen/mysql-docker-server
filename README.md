# 需求

- 这是一个web服务，web服务基于flask构建
- 这个服务需要支持后台开启docker-compose
- 这个服务需要支持后台关闭docker-compose
- 这个服务接受参数，用来生成docker-compose.yml文件内容以及初始化时需要的内容
- 这个服务的docker-compose.yaml文件，主要是用来启动mysql的服务
- 这个服务下的mysql的端口，则需要这个服务来管理
- 这个服务成功启动mysql后，需要返回mysql的连接信息，包括ip、端口、用户名、密码
- 这个服务通过端口来控制启动的mysql进程
- 这个服务开启的总的mysql进程有限制，如果达到最大限制，则需要将需要创建的mysql进程信息保存起来，等有mysql进程关闭后，再创建
- 如果整个web服务关闭，则这个服务需要将所有开启的mysql进程关闭
- mysql进程是在docker-compose.yaml文件中启动的，所以需要通过docker-compose.yaml文件来管理mysql进程 


## 测试

```bash
curl -X POST http://localhost:5600/mysql/start \
     -H "Content-Type: application/json" \
     -d '{"mysql_root_password": "your_password", "init_sql": "CREATE DATABASE test; USE test; CREATE TABLE test_table (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255));"}'
```

```bash
curl -X POST http://localhost:5600/mysql/stop/3306
```