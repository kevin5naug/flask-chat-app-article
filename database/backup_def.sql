create table chat_room(
    chat_room_id varchar(20),
    primary key (chat_room_id)
);

create table user(
    username varchar(50),
    online bit not NULL,
    chat_room_id varchar(20),
    primary key (username),
    foreign key (chat_room_id) references chat_room (chat_room_id)
);
