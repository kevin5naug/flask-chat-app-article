create table user(
    username varchar(50),
    online numeric(50,0) not NULL,
    chat_room_id numeric(50,0),
    primary key (username)
);
