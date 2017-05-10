import tensorflow as tf
import numpy as np
from tensorflow.contrib.rnn import LSTMStateTuple


class Data():
    pass


class AspectLevelModel():
    def __init__(self, cell, hidden_size, vocab_size, aspect_vocab_size, embedding_size,
                 bidirectional=False, aspect_embedding_size=None,
                 attention=False,
                 debug=False):
        self.hidden_size = hidden_size  # d in paper
        self.aspect_vocab_size = aspect_vocab_size
        self.debug = debug
        self.bidirectional = bidirectional
        self.attention = attention

        self.vocab_size = vocab_size
        self.embedding_size = embedding_size
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

        self._init_train_connectors()
        self._init_word_embeddings()

        if self.bidirectional:
            self._init_bidirectional()
        else:
            self._init_simple()

        self._init_optimizer()

    def _init_debug_inputs(self):
        """ Everything is time-major """
        x = [[5, 6, 7],
             [7, 6, 0],
             [0, 7, 0]]
        xl = [2, 3, 1]
        a = [5, 6, 7]
        y = [[1], [0], [1]]
        yl = [1, 1, 1]
        self.inputs = tf.constant(x, dtype=tf.int32, name='inputs')
        self.input_aspect = tf.constant(a, dtype=tf.int32, name='input_aspect')
        self.inputs_length = tf.constant(xl, dtype=tf.int32, name='inputs_length')

        self.targets = tf.constant(y, dtype=tf.int32, name='targets')
        self.targets_length = tf.constant(yl, dtype=tf.int32, name='targets_length')

    def _init_placeholders(self):
        """ Everything is time-major """
        self.inputs = tf.placeholder(
            shape=(None, None),
            dtype=tf.int32,
            name='inputs',
        )
        self.input_aspect = tf.placeholder(
            shape=(None, None),
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
            shape=(None, None),
            dtype=tf.int32,
            name='targets'
        )
        self.targets_length = tf.placeholder(
            shape=(None,),
            dtype=tf.int32,
            name='targets_length',
        )

    def _init_train_connectors(self):
        """
        During training, `decoder_targets`
        and decoder logits. This means that their shapes should be compatible.
        Here we do a bit of plumbing to set this up.
        """
        with tf.name_scope('TrainFeeds'):
            sequence_size, batch_size = tf.unstack(tf.shape(self.targets))

            self.train_inputs = self.inputs
            self.train_length = self.inputs_length

            train_targets = self.targets
            train_targets_seq_len, _ = tf.unstack(tf.shape(train_targets))
            train_targets_eos_mask = tf.one_hot(self.train_length - 1,
                                                train_targets_seq_len,
                                                on_value=self.EOS, off_value=self.PAD,
                                                dtype=tf.int32)
            train_targets_eos_mask = tf.transpose(train_targets_eos_mask, [1, 0])

            # hacky way using one_hot to put EOS symbol at the end of target sequence
            train_targets = tf.add(train_targets,
                                   train_targets_eos_mask)

            self.train_targets = train_targets

            self.loss_weights = tf.ones([batch_size, tf.reduce_max(self.train_length)],
                                        dtype=tf.float32, name="loss_weights")

    def _init_aspect_embeddings(self):
        with tf.variable_scope("AspectEmbedding") as scope:
            # Uniform(-sqrt(3), sqrt(3)) has variance=1.
            sqrt3 = tf.math.sqrt(3)
            initializer = tf.random_uniform_initializer(-sqrt3, sqrt3)

            self.aspect_embedding_matrix = tf.get_variable(
                name="aspect_embedding_matrix",
                shape=[self.aspect_vocab_size, self.aspect_embedding_size],
                initializer=initializer,
                dtype=tf.float32)

            self.input_aspect_embedded = tf.nn.embedding_lookup(
                self.aspect_embedding_matrix, self.input_aspect)  # -> [batch_size, da]
            self.input_aspect_embedded_final = tf.tile(self.input_aspect_embedded,
                                                       (1, self.outputs.shape[1], 1))  # -> [batch_size, N, da]

    def _init_word_embeddings(self):
        with tf.variable_scope("WordEmbedding") as scope:
            # Uniform(-sqrt(3), sqrt(3)) has variance=1.
            sqrt3 = tf.math.sqrt(3)
            initializer = tf.random_uniform_initializer(-sqrt3, sqrt3)

            self.embedding_matrix = tf.get_variable(
                name="word_embedding_matrix",
                shape=[self.vocab_size, self.embedding_size],
                initializer=initializer,
                dtype=tf.float32)

            self.inputs_embedded = tf.nn.embedding_lookup(
                self.embedding_matrix, self.inputs)  # -> [batch_size, N, dw]

            self.inputs_embedded_final = tf.concat([self.inputs_embedded, self.input_aspect_embedded_final],
                                                   2)  # -> [batch_size, N, dw+da]

    def _init_simple(self):
        with tf.variable_scope("RNN") as scope:
            def output_fn(outputs):
                return tf.contrib.layers.fully_connected(outputs, self.vocab_size, scope=scope)

            # shape of state is [batch_size, cell.state_size]
            (self.outputs, self.state) = (
                tf.nn.dynamic_rnn(cell=self.cell,
                                  inputs=self.inputs_embedded_final,
                                  sequence_length=self.inputs_length,
                                  dtype=tf.float32)
            )

            """Not yet implemented - Does not work"""
            Wh = tf.Variable(
                tf.random_normal(shape=[self.hidden_size, self.hidden_size], stddev=1.0 / tf.math.sqrt(600)),
                dtype=tf.float32)  # -> [d, d]
            Wv = tf.Variable(tf.random_normal(shape=[self.aspect_embedding_size, self.aspect_embedding_size],
                                              stddev=1.0 / tf.math.sqrt(600)), dtype=tf.float32)  # -> [da, da]

            w = tf.Variable(tf.random_normal(shape=[self.hidden_size + self.aspect_embedding_size, 1],
                                             stddev=1.0 / tf.math.sqrt(600)), dtype=tf.float32)  # -> [d+da, 1]

            H = tf.reshape(self.outputs, [-1, self.hidden_size])  # -> [batch_size x N, d]
            a_ = tf.matmul(H, Wh)  # -> [batch_size x N, d]
            a = tf.reshape(a_, tf.shape(self.outputs))  # -> [batch_size, N, d]

            # a = tf.stack([tf.matmul(Wh, tf.transpose(state)) for state in self.outputs])

            # input_aspect_embedded shape is [batch_size, da]
            b_ = tf.matmul(self.input_aspect_embedded, Wv)  # [batch_size, da] X [da, da] -> [batch_size, da]
            b = tf.tile(b_, (1, self.outputs.shape[1], 1))  # [batch_size, N, da]

            # b = tf.stack([tf.matmul(Wv, self.input_aspect_embedded) for x in self.inputs_length])
            M = tf.tanh(tf.concat([a, b], 2))  # -> [batch_size, N, d+da]
            M_ = tf.reshape(M, [-1, M.shape[2]])  # -> [batch_size x N, d+da]

            alpha_ = tf.nn.softmax(tf.matmul(M_, w))  # -> [batch_size x N, 1]
            alpha = tf.reshape(alpha_, [-1, self.outputs.shape[1], 1])  # -> [batch_size, N, 1]

            # [batch_size, N, d] x [batch_size, N, 1]
            r = tf.matmul(tf.transpose(self.outputs, [0, 2, 1]), alpha,
                          name='sentence_weighted_representation')

            Wp = tf.Variable(
                tf.random_normal(shape=[self.hidden_size, self.hidden_size], stddev=1.0 / tf.math.sqrt(600)),
                dtype=tf.float32)

            Wx = tf.Variable(
                tf.random_normal(shape=[self.hidden_size, self.hidden_size], stddev=1.0 / tf.math.sqrt(600)),
                dtype=tf.float32)

            # -> ([batch_size, d x 1] x [d, d])  + ([batch_size, d] x [d, d]) = [batch_size, d]
            r_ = tf.reshape(r, [r.shape[0], -1])
            h_star = tf.tanh(tf.add(tf.matmul(r_, Wp), tf.matmul(self.state.h, Wx)), name='sentence_representation')

            Ws = tf.Variable(
                tf.random_normal(shape=[self.hidden_size, self.hidden_size], stddev=1.0 / tf.math.sqrt(600)),
                dtype=tf.float32)

            bs = tf.Variable(tf.zeros(shape=[1, self.hidden_size, 1]))

            e = tf.contrib.layers.linear

            self.y = tf.nn.softmax(tf.add(tf.reshape(tf.matmul(h_star, Ws), [h_star.shape[0], -1, 1]),
                                          tf.tile(bs, (h_star.shape[0], 1, 1))))

            self.logits_train = output_fn(self.outputs)
            self.prediction_train = tf.argmax(self.logits_train, axis=-1,
                                              name='prediction_train')

    def _init_bidirectional(self):
        with tf.variable_scope("BidirectionalRNN") as scope:
            def output_fn(outputs):
                return tf.contrib.layers.linear(outputs, self.vocab_size, scope=scope)

            ((fw_outputs,
              bw_outputs),
             (fw_state,
              bw_state)) = (
                tf.nn.bidirectional_dynamic_rnn(cell_fw=self.cell,
                                                cell_bw=self.cell,
                                                inputs=self.inputs_embedded_final,
                                                sequence_length=self.inputs_length,
                                                time_major=True,
                                                dtype=tf.float32)
            )

            self.outputs = tf.concat((fw_outputs, bw_outputs), 2)

            if isinstance(fw_state, LSTMStateTuple):

                state_c = tf.concat(
                    (fw_state.c, bw_state.c), 1, name='bidirectional_concat_c')
                state_h = tf.concat(
                    (fw_state.h, bw_state.h), 1, name='bidirectional_concat_h')
                self.state = LSTMStateTuple(c=state_c, h=state_h)


            elif isinstance(fw_state, tf.Tensor):
                self.state = tf.concat((fw_state, bw_state), 1, name='bidirectional_concat')

            self.logits_train = output_fn(self.outputs)
            self.prediction_train = tf.argmax(self.logits_train, axis=-1,
                                              name='prediction_train')
            """
            self.prediction_inference = tf.argmax(self.logits_inference, axis=-1,
                                                        name='prediction_inference')
            """

    def _init_optimizer(self):
        logits = tf.transpose(self.logits_train, [1, 0, 2])
        targets = tf.transpose(self.train_targets, [1, 0])

        self.loss = tf.nn.softmax_cross_entropy_with_logits(logits=logits, labels=targets)

        # self.loss = seq2seq.sequence_loss(logits=logits, targets=targets, weights=self.loss_weights)
        self.train_op = tf.train.AdamOptimizer().minimize(self.loss)

    """
    def make_train_inputs(self, input_seq, target_seq):
        inputs_, inputs_length_ = helpers.batch(input_seq)
        targets_, targets_length_ = helpers.batch(target_seq)
        return {
            self.inputs: inputs_,
            self.inputs_length: inputs_length_,
            self.targets: targets_,
            self.targets_length: targets_length_,
        }

    def make_inference_inputs(self, input_seq):
        inputs_, inputs_length_ = helpers.batch(input_seq)
        return {
            self.inputs: inputs_,
            self.inputs_length: inputs_length_,
        }
    """