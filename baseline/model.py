import tensorflow as tf


class Data():
    pass


def load_wv(file_path):
    pass


class AspectLevelModel():
    def __init__(self, cell, hidden_size, vocab_size, aspect_vocab_size, embedding_size, aspect_embedding_size,
                 input_length, batch_size,
                 bidirectional=False,
                 attention=False,
                 debug=False):
        self.hidden_size = hidden_size  # d in paper
        self.aspect_vocab_size = aspect_vocab_size
        self.debug = debug
        self.bidirectional = bidirectional
        self.attention = attention

        self.vocab_size = vocab_size
        self.embedding_size = embedding_size
        self.N = input_length
        self.batch_size = batch_size

        self.l2_reg = 0.01

        self.class_size = 3
        if cell == 'lstm':
            self.cell = tf.contrib.rnn.BasicLSTMCell(hidden_size)
        elif cell == 'gru':
            self.cell = tf.contrib.rnn.GRUCell(hidden_size)
        self.aspect_embedding_size = aspect_embedding_size  # da in paper

        self.__init_graph__()

    def __init_graph__(self):
        if self.debug:
            self._init_debug_inputs()
        else:
            self._init_placeholders()

        self._init_aspect_embeddings()
        self._init_word_embeddings()

        if self.bidirectional:
            self._init_simple()
        else:
            self._init_simple()

        self._init_optimizer()

    def _init_debug_inputs(self):
        """ Everything is time-major """
        x = [[5, 6, 1],
             [7, 6, 0],
             [0, 7, 0],
             [1, 2, 3]]
        xl = [3, 2, 2, 3]
        a = [1, 4, 2, 5]
        y = [[0, 1, 0],
             [1, 0, 0],
             [0, 0, 1],
             [0, 1, 0]]
        self.inputs = tf.constant(x, dtype=tf.int32, name='inputs')
        self.input_aspect = tf.constant(a, dtype=tf.int32, name='input_aspect')
        self.inputs_length = tf.constant(xl, dtype=tf.int32, name='inputs_length')

        self.targets = tf.constant(y, dtype=tf.int32, name='targets')

    def _init_placeholders(self):
        self.keep_prob1 = tf.placeholder(tf.float32)
        # self.keep_prob2 = tf.placeholder(tf.float32)
        # input
        self.inputs = tf.placeholder(
            shape=(None, self.N),
            dtype=tf.int32,
            name='inputs',
        )
        # self.inputs = tf.nn.dropout(self.inputs, keep_prob=self.keep_prob1)
        self.input_aspect = tf.placeholder(
            shape=(None,),
            dtype=tf.int32,
            name='input_aspect',
        )
        self.inputs_length = tf.placeholder(
            shape=(None,),
            dtype=tf.int32,
            name='inputs_length',
        )

        # required for training, not required for testing
        self.targets = tf.placeholder(
            shape=(None, self.class_size),
            dtype=tf.int32,
            name='targets'
        )

    def _init_aspect_embeddings(self):
        with tf.variable_scope("AspectEmbedding") as scope:
            self.input_shape = tf.shape(self.inputs)
            # Uniform(-sqrt(3), sqrt(3)) has variance=1.
            sqrt3 = tf.sqrt(3.0)
            initializer = tf.random_uniform_initializer(-sqrt3, sqrt3)

            """self.aspect_embedding_matrix = tf.get_variable(
                name="aspect_embedding_matrix",
                shape=[self.aspect_vocab_size, self.aspect_embedding_size],
                initializer=initializer,
                dtype=tf.float32)"""
            self.aspect_embedding_matrix = tf.Variable(
                tf.constant(0.0, shape=[self.aspect_vocab_size, self.aspect_embedding_size]),
                trainable=False, name="aspect_embedding_matrix")
            self.aspect_embedding_placeholder = tf.placeholder(tf.float32,
                                                               [self.aspect_vocab_size, self.aspect_embedding_size])
            self.aspect_embedding_init = self.aspect_embedding_matrix.assign(self.aspect_embedding_placeholder)

            self.input_aspect_embedded = tf.nn.embedding_lookup(
                self.aspect_embedding_matrix, self.input_aspect)  # -> [batch_size, da]
            s = tf.shape(self.input_aspect_embedded)
            self.input_aspect_embedded_final = tf.tile(tf.reshape(self.input_aspect_embedded, (s[0], -1, s[1])),
                                                       (1, self.input_shape[1], 1))  # -> [batch_size, N, da]

    def _init_word_embeddings(self):
        with tf.variable_scope("WordEmbedding") as scope:
            """
            self.embedding_matrix = tf.get_variable(
                name="word_embedding_matrix",
                shape=[self.vocab_size, self.embedding_size],
                initializer=initializer,
                dtype=tf.float32)
            """
            self.embedding_matrix = tf.Variable(
                tf.constant(0.0, shape=[self.vocab_size, self.embedding_size]),
                trainable=False, name="embedding_matrix")
            self.embedding_placeholder = tf.placeholder(tf.float32,
                                                        [self.vocab_size, self.embedding_size])
            self.embedding_init = self.embedding_matrix.assign(self.embedding_placeholder)

            self.inputs_embedded = tf.nn.embedding_lookup(
                self.embedding_matrix, self.inputs)  # -> [batch_size, N, dw]

            self.inputs_embedded_final = tf.concat([self.inputs_embedded, self.input_aspect_embedded_final],
                                                   2)  # -> [batch_size, N, dw+da]
            self.inputs_embedded_final = tf.nn.dropout(self.inputs_embedded_final, keep_prob=self.keep_prob1)

            # self.batch_size = int(self.inputs.get_shape()[0])
            self.N = int(self.inputs.get_shape()[1])

            self.inputs_embedded_final = tf.reshape(self.inputs_embedded_final,
                                                    [self.batch_size, self.N,
                                                     self.embedding_size + self.aspect_embedding_size])

    def _init_simple(self):
        with tf.variable_scope("RNN") as scope:
            print("inputs_embedded_final : ", self.inputs_embedded_final.get_shape())
            # shape of state is [batch_size, cell.state_size]
            (self.outputs, self.state) = (
                tf.nn.dynamic_rnn(cell=self.cell,
                                  inputs=self.inputs_embedded_final,
                                  sequence_length=self.inputs_length,
                                  dtype=tf.float32)
            )
            batch_size = self.batch_size
            N = self.N
            da = self.aspect_embedding_size
            d = self.hidden_size

            Wh = tf.Variable(
                tf.random_normal(shape=[self.hidden_size, self.hidden_size], stddev=1.0 / tf.sqrt(600.0)),
                dtype=tf.float32)  # -> [d, d]
            Wv = tf.Variable(tf.random_normal(shape=[self.aspect_embedding_size, self.aspect_embedding_size],
                                              stddev=1.0 / tf.sqrt(600.0)), dtype=tf.float32)  # -> [da, da]

            w = tf.get_variable(
                name='w',
                shape=[self.hidden_size + self.aspect_embedding_size, 1],
                initializer=tf.random_uniform_initializer(-0.003, 0.003),
                regularizer=tf.contrib.layers.l2_regularizer(self.l2_reg)
            )

            # w = tf.Variable(tf.random_normal(shape=[self.hidden_size + self.aspect_embedding_size, 1],
            #                                 stddev=1.0 / tf.sqrt(600.0)), dtype=tf.float32)  # -> [d+da, 1]

            H = tf.reshape(self.outputs, [-1, self.hidden_size])  # -> [batch_size x N, d]
            print("H: ", H.get_shape())
            a_ = tf.matmul(H, Wh)  # -> [batch_size x N, d]
            a = tf.reshape(a_, tf.shape(self.outputs))  # -> [batch_size, N, d]
            print("a: ", a.get_shape())

            # input_aspect_embedded shape is [batch_size, da]
            b_ = tf.matmul(self.input_aspect_embedded, Wv)  # [batch_size, da] X [da, da] -> [batch_size, da]

            b = tf.reshape(b_, [-1, 1, da])  # -> [batch_size, 1, da]
            print("b: ", b.get_shape())
            b = tf.tile(b, (1, N, 1))  # [batch_size, N, da]
            print("b: ", b.get_shape())

            M = tf.tanh(tf.concat([a, b], 2))  # -> [batch_size, N, d+da]
            M_ = tf.reshape(M, [batch_size * N, d + da])  # -> [batch_size x N, d+da]
            print("M_: ", M_.get_shape())

            alpha_ = tf.nn.softmax(tf.matmul(M_, w))  # -> [batch_size x N, 1]
            alpha = tf.reshape(alpha_, [batch_size, N, 1])  # -> [batch_size, N, 1]
            print("alpha: ", alpha.get_shape())

            # [batch_size, N, d] x [batch_size, N, 1]
            r = tf.matmul(tf.transpose(self.outputs, [0, 2, 1]), alpha,
                          name='sentence_weighted_representation')
            print("r", r.get_shape())

            Wp = tf.Variable(
                tf.random_normal(shape=[self.hidden_size, self.hidden_size], stddev=1.0 / tf.sqrt(600.0)),
                dtype=tf.float32)

            Wx = tf.Variable(
                tf.random_normal(shape=[self.hidden_size, self.hidden_size], stddev=1.0 / tf.sqrt(600.0)),
                dtype=tf.float32)

            # -> ([batch_size, d x 1] x [d, d])  + ([batch_size, d] x [d, d]) = [batch_size, d]
            r_ = tf.reshape(r, [batch_size, d])
            print("r_: ", r_.get_shape())

            h_star = tf.tanh(tf.add(tf.matmul(r_, Wp), tf.matmul(self.state.h, Wx)),
                             name='sentence_representation')  # -> [1, d]
            h_star = tf.reshape(h_star, [batch_size, d])

            print("h*: ", h_star.get_shape())

            Ws = tf.Variable(
                tf.random_normal(shape=[self.hidden_size, self.class_size], stddev=1.0 / tf.sqrt(600.0)),
                dtype=tf.float32)

            bs = tf.Variable(tf.zeros(shape=[1, self.class_size]))

            # Ws - > [d, c] , h* -> [batch_size, d]
            # [batch_size, d] x [d, c] = [batch_size, c]
            e = tf.add(tf.reshape(tf.matmul(h_star, Ws), [batch_size, self.class_size]),
                       tf.tile(bs, (batch_size, 1)))
            print("e: ", e.get_shape())
            # y -> [batch_size, class_size]
            self.y = tf.nn.softmax(e)
            print("y: ", self.y.get_shape())

            self.logits_train = self.y
            print("logits_train: ", self.logits_train.get_shape())
            self.prediction_train = tf.reshape(tf.argmax(self.logits_train, axis=-1,
                                                         name='prediction_train'), [batch_size, -1])
            print("prediction_train: ", self.prediction_train.get_shape())

    def _init_optimizer(self):
        reg_lambda = 0.001
        # self.loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.logits_train, labels=self.targets))
        self.loss = - tf.reduce_mean(tf.cast(self.targets, tf.float32) * tf.log(self.logits_train)) + tf.reduce_sum(
            [reg_lambda * tf.nn.l2_loss(x) for x in tf.trainable_variables()])
        self.train_op = tf.train.AdamOptimizer(0.01).minimize(self.loss)
